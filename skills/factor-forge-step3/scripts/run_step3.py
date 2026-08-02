#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from datetime import timedelta
from pathlib import Path

import pandas as pd

# Runtime root policy:
# - prefer FACTORFORGE_ROOT when explicitly configured
# - otherwise keep legacy EC2 compatibility
# - fallback to current repository root for local runs
# COMMENT_POLICY: runtime_path
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
LEGACY_REPO_ROOT = LEGACY_WORKSPACE / 'repos' / 'factor-factory'
REPO_ROOT = Path(os.getenv('FACTORFORGE_REPO_ROOT')).expanduser() if os.getenv('FACTORFORGE_REPO_ROOT') else (LEGACY_REPO_ROOT if LEGACY_REPO_ROOT.exists() else Path(__file__).resolve().parents[3])
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_access import (
    CleanDailyLayerPaths,
    clean_daily_layer_ready,
    inspect_trade_date_csv_root,
    minute_derived_flow_state_requirement,
    research_window_contract,
    resolve_clean_daily_layer_paths,
    resolve_local_tushare_paths,
)
from factor_factory.data_api import default_catalog_path, fetch_data_api_dataset, resolve_data_api_dataset
from factor_factory.formula.field_aliases import aliases_for
from factor_factory.runtime_context import load_runtime_manifest, manifest_factorforge_root, manifest_report_id
from factor_factory.step3.template_runtime import maybe_reexec_from_template_copy

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
MONEYFLOW_DATASET_FIELDS = [
    'ts_code',
    'trade_date',
    'buy_sm_amount',
    'sell_sm_amount',
    'buy_md_amount',
    'sell_md_amount',
    'buy_lg_amount',
    'sell_lg_amount',
    'buy_elg_amount',
    'sell_elg_amount',
    'net_mf_amount',
]
MONEYFLOW_SIGNAL_FIELDS = set(MONEYFLOW_DATASET_FIELDS) - {'ts_code', 'trade_date'}
DAILY_BASIC_DATASET_FIELDS = [
    'ts_code',
    'trade_date',
    'turnover_rate',
    'turnover_rate_f',
    'volume_ratio',
    'pe',
    'pe_ttm',
    'pb',
    'ps',
    'ps_ttm',
    'dv_ratio',
    'dv_ttm',
    'total_share',
    'float_share',
    'free_share',
    'total_mv',
    'circ_mv',
]


def select_daily_basic_fields_for_required_formula_fields(required_fields: list[str] | None) -> list[str]:
    required_set = {str(field).strip().lower() for field in (required_fields or []) if str(field).strip()}
    expanded_required = set(required_set)
    for field in list(required_set):
        try:
            expanded_required.update(str(alias).strip().lower() for alias in aliases_for(field))
        except KeyError:
            continue
    return [
        field for field in DAILY_BASIC_DATASET_FIELDS
        if field in {'ts_code', 'trade_date'} or field in expanded_required
    ]


def select_clean_daily_fields_for_formula(
    required_fields: list[str] | None,
    formula_ir: dict | None,
) -> list[str]:
    """Bind Step3/Step4 Data API queries to the validated Formula IR schema."""
    fields = ['open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg']
    resolved = (
        formula_ir.get('resolved_fields')
        if isinstance(formula_ir, dict) and isinstance(formula_ir.get('resolved_fields'), dict)
        else {}
    )
    candidates = [
        str(resolved.get(str(field)) or field).strip().lower()
        for field in (required_fields or [])
        if str(field).strip()
    ]
    derived = {'volume', 'returns', 'return', 'ret', 'vwap'}
    daily_basic = set(DAILY_BASIC_DATASET_FIELDS)
    for field in candidates:
        if (
            field in derived
            or _adv_window(field) is not None
            or field in daily_basic
            or field in MONEYFLOW_SIGNAL_FIELDS
            or field in {'ts_code', 'trade_date'}
        ):
            continue
        if field not in fields:
            fields.append(field)
    return fields

DIRECT_CODE_ALLOWED_SOURCE_DERIVATIONS = {
    'source_code_preserved_from_formal_step2_raw_direct_code_contract',
    'source_code_preserved_from_step2_direct_code_contract',
    'source_code_generated_by_step3a_llm_provider',
}
INTRADAY_PROXY_DATASETS = {'intraday_flow_proxy_daily', 'clean_minute_bar'}
MINUTE_DERIVED_FLOW_STATE_DATASET = 'minute_derived_flow_state_v1'
INTRADAY_RETAINED_CHIP_STATE_DATASET = 'intraday_retained_chip_state_v1'
RETAINED_CHIP_STATE_FIELDS = [
    'ts_code',
    'trade_date',
    'lcr_raw',
    'retained_amount_sum',
    'amount_sum_20d',
    'interval_turnover_sum_20d',
    'survival_weighted_interval_count',
    'interval_count',
    'valid_interval_count',
    'lookback_days',
    'interval_minutes',
    'turnover_denominator_source',
    'float_share',
    'float_share_unit',
    'amount_unit',
    'source_min_date',
    'source_max_date',
    'missing_interval_count',
    'turnover_clipped_count',
    'qa_status',
]
DEFAULT_MINUTE_DERIVED_CUTOFF_TIME = '14:50:00'
STEP3_TEMPLATE_COPY_ENV = 'FACTORFORGE_STEP3_TEMPLATE_COPY'
STEP3_TEMPLATE_COPY_VERSION = 'factorforge_step3_template_copy_v1'


def data_api_dataset_registered(dataset_id: str) -> tuple[bool, str | None]:
    catalog_path = default_catalog_path()
    if catalog_path is None or not catalog_path.exists():
        return False, str(catalog_path) if catalog_path else None
    try:
        catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    except Exception:
        return False, str(catalog_path)
    raw = catalog.get('datasets', catalog)
    if isinstance(raw, dict):
        return dataset_id in raw, str(catalog_path)
    if isinstance(raw, list):
        return any(isinstance(item, dict) and item.get('dataset_id') == dataset_id for item in raw), str(catalog_path)
    return False, str(catalog_path)


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


def maybe_reexec_from_step3_template_copy(report_id: str | None, manifest_path: str | None) -> None:
    maybe_reexec_from_template_copy(
        script_stem='run_step3',
        report_id=report_id,
        manifest_path=manifest_path,
        default_factorforge_root=FF,
        source_path=Path(__file__),
        copy_env=STEP3_TEMPLATE_COPY_ENV,
        copy_version=STEP3_TEMPLATE_COPY_VERSION,
        policy='canonical_run_step3_py_is_template_only',
        template_path_env='FACTORFORGE_STEP3_TEMPLATE_PATH',
        runtime_copy_path_env='FACTORFORGE_STEP3_RUNTIME_COPY_PATH',
    )


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

    # Step2/factor_spec is the authoritative source for direct_code contracts.
    # A previous Step3 run may have written an implementation_plan with stale
    # source_code; do not let that old plan override a refreshed formal
    # contract when Step3A is rerun.
    if _contract_has_source(updates):
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


def current_data_api_end_date() -> str:
    override = _normalize_window_date(os.getenv('FACTORFORGE_DATA_API_CURRENT_END_DATE'))
    if override and override != 'current':
        return override
    return datetime.now(timezone.utc).strftime('%Y%m%d')


def _data_api_window_bound(value, *, default: str, current_sentinel: str | None = None) -> str:
    normalized = _normalize_window_date(value)
    if not normalized:
        return default
    if normalized == 'current':
        return current_sentinel or default
    return normalized


def data_api_window_bounds(sample_window: dict) -> dict:
    return {
        'start': _data_api_window_bound(sample_window.get('start'), default='19000101'),
        'end': _data_api_window_bound(sample_window.get('end'), default=current_data_api_end_date(), current_sentinel=current_data_api_end_date()),
    }


def step3a_formula_sample_calendar_days(formula_ir: dict | None, *, default_calendar_days: int = 220) -> tuple[int, int]:
    """Return a bounded Step3B proof span large enough for formula lookbacks."""
    max_lookback = max_formula_ir_lookback(formula_ir)
    if max_lookback <= 0:
        return default_calendar_days, max_lookback
    # Step3B is still only an executability proof, but a formula with long
    # rolling windows needs enough trading days to produce non-null samples.
    # Calendar days are a conservative proxy for A-share trading days.
    calendar_days = int(max_lookback * 1.7) + 60
    return max(default_calendar_days, min(calendar_days, 900)), max_lookback


def step3a_executability_window(sample_window: dict, *, max_calendar_days: int | None = None, formula_ir: dict | None = None) -> dict:
    """Use a bounded real-data window for Step3B code proof; Step4 owns full execution."""
    inferred_calendar_days, formula_max_lookback = step3a_formula_sample_calendar_days(formula_ir)
    if max_calendar_days is None:
        max_calendar_days = inferred_calendar_days
    bounds = data_api_window_bounds(sample_window)
    start = bounds['start']
    end = bounds['end']
    if re.fullmatch(r'\d{8}', start) and re.fullmatch(r'\d{8}', end):
        start_dt = datetime.strptime(start, '%Y%m%d')
        end_dt = datetime.strptime(end, '%Y%m%d')
        capped_end = min(end_dt, start_dt + timedelta(days=max_calendar_days))
        end = capped_end.strftime('%Y%m%d')
    return {
        'start': start,
        'end': end,
        'calendar': sample_window.get('calendar') or 'A-share trading days',
        'source_window': {
            'start': bounds['start'],
            'end': bounds['end'],
            'calendar': sample_window.get('calendar') or 'A-share trading days',
        },
        'bounded_for': 'step3b_executability_proof',
        'full_execution_owner': 'Step4',
        'max_calendar_days': max_calendar_days,
        'formula_max_lookback': formula_max_lookback,
        'sample_window_policy': 'bounded_by_formula_lookback',
    }


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
            '_allow_partial_window': True,
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
        if candidate.get('_allow_partial_window') and (start or end):
            return {
                'start': start or fallback.get('start') or '20100104',
                'end': end or fallback.get('end') or 'current',
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


def _state_dependency_dataset_ids(fsm: dict) -> set[str]:
    ids: set[str] = set()
    candidates = [
        fsm.get('state_dependency_contract'),
        (fsm.get('implementation_contract') or {}).get('state_dependency_contract')
        if isinstance(fsm.get('implementation_contract'), dict) else None,
        (fsm.get('canonical_spec') or {}).get('state_dependency_contract')
        if isinstance(fsm.get('canonical_spec'), dict) else None,
    ]
    for contract in candidates:
        if not isinstance(contract, dict):
            continue
        for item in contract.get('required_datasets') or []:
            if isinstance(item, dict) and item.get('dataset_id'):
                ids.add(str(item['dataset_id']).strip())
    return ids


def direct_code_uses_retained_chip_state(fsm: dict) -> bool:
    return INTRADAY_RETAINED_CHIP_STATE_DATASET in _state_dependency_dataset_ids(fsm)


def retained_chip_state_requirement(
    *,
    start_date: str,
    end_date: str,
    catalog_path: str | None = None,
) -> dict:
    return {
        'dataset_id': INTRADAY_RETAINED_CHIP_STATE_DATASET,
        'schema_version': 'intraday_retained_chip_state_v1_p0',
        'start_date': start_date,
        'end_date': end_date,
        'frequency': 'daily',
        'cutoff_time': '15:00:00',
        'required_fields': RETAINED_CHIP_STATE_FIELDS,
        'catalog_path': catalog_path,
        'state_asof': 'selection_trade_date_close',
        'no_future_data': True,
        'no_future_intraday_minutes': True,
        'raw_minute_full_window_allowed': False,
    }


def append_retained_chip_state_adapter(source: str) -> str:
    if 'def compute_factor_from_derived_state' in source and 'def compute_factor' in source:
        return source if source.endswith('\n') else source + '\n'
    adapter = '''

def compute_factor_from_derived_state(daily_df=None, derived_state_df=None):
    """Map the production retained-chip state datamart to formal factor values."""
    import pandas as pd

    if derived_state_df is None:
        raise ValueError("derived_state_df is required for intraday_retained_chip_state_v1")
    frame = derived_state_df.copy()
    required = {"ts_code", "trade_date", "lcr_raw"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"intraday_retained_chip_state_v1 missing columns: {sorted(missing)}")
    out = frame.loc[:, ["ts_code", "trade_date", "lcr_raw"]].copy()
    out["factor_value"] = pd.to_numeric(out["lcr_raw"], errors="coerce")
    out = out.drop(columns=["lcr_raw"])
    out = out.dropna(subset=["factor_value"])
    return out


def compute_factor(daily_df=None, minute_df=None, derived_state_df=None):
    """Step3B/Step4 adapter; minute_df may carry the retained-chip state sample."""
    state_df = derived_state_df if derived_state_df is not None else minute_df
    return compute_factor_from_derived_state(daily_df=daily_df, derived_state_df=state_df)
'''
    return source.rstrip() + adapter


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
    uses_retained_state = direct_code_uses_retained_chip_state(fsm)
    if existing_source:
        source = existing_source if existing_source.endswith('\n') else existing_source + '\n'
        if uses_retained_state:
            source = append_retained_chip_state_adapter(source)
        source_derivation = existing_code_contract.get('source_derivation') if isinstance(existing_code_contract.get('source_derivation'), dict) else {}
        raw_derivation = str(source_derivation.get('derivation') or 'source_code_preserved_from_step2_direct_code_contract')
        derivation = raw_derivation
        if derivation not in DIRECT_CODE_ALLOWED_SOURCE_DERIVATIONS:
            derivation = 'source_code_preserved_from_step2_direct_code_contract'
    else:
        return {
            'status': 'blocked',
            'blocked_reason': 'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: Step2 direct_code contract must explicitly provide code_contract.source_code',
        }

    if uses_retained_state:
        required_fields = list(RETAINED_CHIP_STATE_FIELDS)
    elif existing_code_contract.get('required_fields'):
        required_fields = list(dict.fromkeys(
            list(existing_code_contract.get('required_fields') or [])
            + ['ts_code', 'trade_date']
        ))
    else:
        required_fields = list(dict.fromkeys(
            list(contract.get('required_fields') or [])
            + list(canonical.get('required_inputs') or [])
            + ['ts_code', 'trade_date']
        ))
    # Explicit direct_code contracts can target non-OHLCV daily panels such as
    # moneyflow. Do not silently append price/volume fields unless Step2 did
    # not provide a source contract field list.
    if not existing_code_contract.get('required_fields'):
        if 'vol' not in required_fields and 'volume' not in required_fields:
            required_fields.append('vol')
        if 'close' not in required_fields:
            required_fields.append('close')
    if uses_retained_state:
        output_schema = {'columns': ['ts_code', 'trade_date', 'factor_value']}
    else:
        output_schema = (
            existing_code_contract.get('output_schema')
            or contract.get('output_schema')
            or {'columns': ['ts_code', 'trade_date', 'factor_value']}
        )
    imports = list(dict.fromkeys(list(existing_code_contract.get('imports') or []) + ['numpy', 'pandas']))
    input_schema = existing_code_contract.get('input_schema') or {
        'daily_df': list((qlib_adapter_config.get('logical_fields') or {}).values()),
        'minute_df': ['ts_code', 'trade_date', 'trade_time', 'close', 'vol', 'amount'],
    }
    if uses_retained_state:
        input_schema = {
            'daily_df': 'optional; not used by the retained-chip state adapter',
            'derived_state_df': RETAINED_CHIP_STATE_FIELDS,
            'state_dataset': INTRADAY_RETAINED_CHIP_STATE_DATASET,
        }
    forbidden_patterns = existing_code_contract.get('forbidden_patterns') or [
        r'shift\s*\(\s*-\d+',
        r'\bfuture_return\b',
        r'\bnext_return\b',
        r'\blabel\b',
        r'\btarget\b',
        r'\bfuture_',
        r'\blookahead\b',
    ]
    if uses_retained_state:
        forbidden_patterns = [
            r'shift\s*\(\s*-\d+',
            r'\bfuture_return\b',
            r'\bnext_return\b',
            r'\bnext_ret\b',
            r'\blabel\b',
            r'\btarget\b',
            r'\bfuture_',
            r'\blookahead\b',
        ]
    code_contract = {
        **existing_code_contract,
        'code_contract_version': existing_code_contract.get('code_contract_version') or DIRECT_CODE_CONTRACT_VERSION,
        'function_name': 'compute_factor' if uses_retained_state else (existing_code_contract.get('function_name') or contract.get('function_name') or 'compute_factor'),
        'entrypoint': 'compute_factor' if uses_retained_state else (existing_code_contract.get('entrypoint') or contract.get('entrypoint') or 'compute_factor'),
        'source_code': source,
        'code_hash': source_hash(source),
        'imports': imports,
        'dependencies': list(dict.fromkeys(list(existing_code_contract.get('dependencies') or []) + imports)),
        'input_schema': input_schema,
        'output_schema': output_schema,
        'required_fields': required_fields,
        'information_set_rules': existing_code_contract.get('information_set_rules') or ['no future-looking fields or negative shifts'],
        'forbidden_patterns': forbidden_patterns,
        'source_derivation': {
            **source_derivation,
            'derivation': derivation,
            'raw_step2_derivation': raw_derivation,
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
    query_window = data_api_window_bounds(sample_window)
    return {
        'dataset': dataset,
        'start_date': query_window['start'],
        'end_date': query_window['end'],
        'universe': universe,
        'fields': list(dict.fromkeys(fields)),
        'frequency': frequency,
    }


def build_step4_data_contract(
    *,
    sample_window: dict,
    daily_resolution: dict | None = None,
    minute_resolution: dict | None = None,
    moneyflow_resolution: dict | None = None,
    daily_basic_resolution: dict | None = None,
    daily_fields: list[str] | None = None,
    minute_fields: list[str] | None = None,
    moneyflow_fields: list[str] | None = None,
    daily_basic_fields: list[str] | None = None,
    minute_derived_state_requirements: list[dict] | None = None,
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
    if moneyflow_resolution:
        fields = moneyflow_fields or MONEYFLOW_DATASET_FIELDS
        full_queries['moneyflow'] = data_api_query_payload('moneyflow', sample_window, fields)
        sample_queries['moneyflow'] = data_api_query_payload(
            'moneyflow',
            sample_window,
            fields,
            universe=['000001.SZ', '000002.SZ'],
        )
    if daily_basic_resolution:
        fields = daily_basic_fields or DAILY_BASIC_DATASET_FIELDS
        full_queries['daily_basic'] = data_api_query_payload('daily_basic', sample_window, fields)
        sample_queries['daily_basic'] = data_api_query_payload(
            'daily_basic',
            sample_window,
            fields,
            universe=['000001.SZ', '000002.SZ'],
        )
    catalog_path = None
    for resolution in [daily_resolution, minute_resolution, moneyflow_resolution, daily_basic_resolution]:
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
        'minute_derived_state_requirements': minute_derived_state_requirements or [],
        'research_window_contract': research_window_contract(sample_window),
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
    contract = fsm.get('implementation_contract') if isinstance(fsm.get('implementation_contract'), dict) else {}
    code_contract = contract.get('code_contract') if isinstance(contract.get('code_contract'), dict) else {}
    candidates = (
        list(formula_ir.get('required_fields') or [])
        + list(canonical.get('required_inputs') or [])
        + list(code_contract.get('required_fields') or [])
        + list(contract.get('required_fields') or [])
        + list(fsm.get('required_inputs') or [])
    )
    return list(dict.fromkeys(str(field).strip().lower() for field in candidates if str(field).strip()))


def moneyflow_required_fields(fsm: dict) -> list[str]:
    required = formula_required_daily_fields(fsm)
    if not any(field in MONEYFLOW_SIGNAL_FIELDS for field in required):
        return []
    fields = ['ts_code', 'trade_date']
    for field in required:
        if field in MONEYFLOW_SIGNAL_FIELDS and field not in fields:
            fields.append(field)
    return fields


def _formula_ir_constants(node) -> list[float]:
    if not isinstance(node, dict):
        return []
    if node.get('type') == 'constant':
        try:
            return [float(node.get('value'))]
        except (TypeError, ValueError):
            return []
    constants: list[float] = []
    for child in node.get('args') or []:
        constants.extend(_formula_ir_constants(child))
    return constants


def _operator_lookback(operator: str, constants: list[float]) -> int | None:
    operator = str(operator or '').strip().lower()
    if operator in {
        'delay', 'delta', 'correlation', 'corr', 'covariance', 'sum', 'mean', 'std',
        'ts_rank', 'min', 'max', 'argmax', 'argmin', 'decay_linear',
    } and constants:
        last = constants[-1]
        if isinstance(last, float) and not last.is_integer():
            return None
        value = int(last)
        return value if value > 0 else None
    return None


def max_formula_ir_lookback(formula_ir: dict | None) -> int:
    if not isinstance(formula_ir, dict):
        return 0
    root = formula_ir.get('root') if isinstance(formula_ir.get('root'), dict) else {}
    lookbacks: list[int] = []

    def visit(node) -> None:
        if not isinstance(node, dict):
            return
        if node.get('type') == 'operator':
            lookback = _operator_lookback(
                str(node.get('operator') or ''),
                _formula_ir_constants(node),
            )
            if lookback is not None:
                lookbacks.append(lookback)
        for child in node.get('args') or []:
            visit(child)

    visit(root)
    return max(lookbacks) if lookbacks else 0


def _formula_ir_fields(node) -> list[str]:
    if not isinstance(node, dict):
        return []
    if node.get('type') == 'field':
        field = node.get('resolved_field') or node.get('name')
        return [str(field).strip().lower()] if str(field or '').strip() else []
    fields: list[str] = []
    for child in node.get('args') or []:
        fields.extend(_formula_ir_fields(child))
    return list(dict.fromkeys(fields))


def formula_ir_has_operator(formula_ir: dict | None, operator_names: set[str]) -> bool:
    if not isinstance(formula_ir, dict):
        return False
    wanted = {str(name).strip().lower() for name in operator_names}

    def visit(node) -> bool:
        if not isinstance(node, dict):
            return False
        if node.get('type') == 'operator':
            operator = str(node.get('operator') or '').strip().lower()
            if operator in wanted:
                return True
        return any(visit(child) for child in (node.get('args') or []))

    return visit(formula_ir.get('root'))


def requires_cross_sectional_sample(formula_ir: dict | None) -> bool:
    return formula_ir_has_operator(formula_ir, {'rank', 'scale', 'cs_regression', 'regression'})


def _field_unit(field: str) -> str:
    field = str(field or '').strip().lower()
    if field in {'open', 'high', 'low', 'close', 'pre_close', 'vwap'}:
        return 'price'
    if field in {'volume', 'vol'} or field.startswith('adv'):
        return 'documented_volume_unit'
    if field == 'amount':
        return 'documented_amount_unit'
    if field in {'returns', 'return', 'ret', 'pct_chg'}:
        return 'documented_return_unit'
    return 'numeric'


def _operator_output_unit(operator: str, child_units: list[str]) -> str:
    operator = str(operator or '').lower()
    if operator in {'rank', 'ts_rank'}:
        return 'rank_score'
    if operator in {'correlation', 'corr'}:
        return 'dimensionless_correlation'
    if operator == 'covariance':
        return 'source_unit_product'
    if operator in {'argmax', 'argmin'}:
        return 'window_position'
    if operator == 'delay':
        return child_units[0] if child_units else 'numeric'
    units = {str(unit) for unit in child_units if str(unit)}
    if operator in {'plus', 'minus'} and units == {'rank_score'}:
        return 'composite_rank_score'
    if len(units) == 1:
        return next(iter(units))
    return 'numeric'


def _formula_ir_output_unit(node) -> str:
    if not isinstance(node, dict):
        return 'numeric'
    if node.get('type') == 'field':
        return _field_unit(str(node.get('resolved_field') or node.get('name') or ''))
    if node.get('type') == 'constant':
        return 'numeric'
    if node.get('type') != 'operator':
        return 'numeric'
    operator = str(node.get('operator') or '').strip().lower()
    child_units = [_formula_ir_output_unit(child) for child in (node.get('args') or [])]
    return _operator_output_unit(operator, child_units)


def formula_operator_contract_specs(formula_ir: dict | None) -> dict[str, dict]:
    if not isinstance(formula_ir, dict):
        return {}
    root = formula_ir.get('root') if isinstance(formula_ir.get('root'), dict) else {}
    contracts: dict[str, dict] = {}
    counter = 0

    def visit(node) -> None:
        nonlocal counter
        if not isinstance(node, dict):
            return
        for child in node.get('args') or []:
            visit(child)
        if node.get('type') != 'operator':
            return
        operator = str(node.get('operator') or '').strip().lower()
        if not operator:
            return
        sources = _formula_ir_fields(node) or ['constant']
        child_units = [_formula_ir_output_unit(child) for child in (node.get('args') or [])]
        spec = {
            'operator': operator,
            'sources': sources,
            'rule': 'formula_ir_operator_semantics',
            'source_units': {source: _field_unit(source) for source in sources},
            'output_unit': _operator_output_unit(operator, child_units),
            'leakage_policy': 'no future data',
        }
        lookback = _operator_lookback(operator, _formula_ir_constants(node))
        if lookback is not None:
            spec['lookback_window'] = lookback
        if operator == 'rank':
            spec['rank_scope'] = 'cross_sectional_by_trade_date'
        contracts[f'operator_{counter:03d}_{operator}'] = spec
        counter += 1

    visit(root)
    return contracts


def _derived_alias_spec(field: str, sources: list[str], rule: str, output_unit: str, *, operator: str = 'alias', lookback_window: int | None = None) -> dict:
    spec = {
        'operator': operator,
        'sources': sources,
        'rule': rule,
        'source_units': {source: _field_unit(source) for source in sources},
        'output_unit': output_unit,
        'leakage_policy': 'no future data',
    }
    if lookback_window is not None:
        spec['lookback_window'] = lookback_window
    return spec


def enrich_report_local_daily_fields(
    daily_df: pd.DataFrame,
    required_fields: list[str],
    formula_ir: dict | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Materialize standard formula aliases in the report-local snapshot only."""
    required = {str(field).strip().lower() for field in (required_fields or [])}
    adv_fields = sorted((field, _adv_window(field)) for field in required if _adv_window(field) is not None)
    needs_volume = 'volume' in required or bool(adv_fields) or 'vwap' in required
    needs_returns = 'returns' in required or 'return' in required or 'ret' in required
    needs_vwap = 'vwap' in required

    added: list[str] = []
    sources: dict[str, str] = {}
    derived_fields: dict[str, dict] = {}
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
        derived_fields['volume'] = _derived_alias_spec(
            'volume',
            [volume_col],
            f'alias(volume <- {volume_col})',
            'documented_volume_unit',
        )
        volume_col = 'volume'

    if needs_returns and 'returns' not in working.columns:
        return_col = 'return' if 'return' in working.columns else 'pct_chg' if 'pct_chg' in working.columns else None
        if return_col is None:
            raise SystemExit('BLOCK_FACTORFORGE_STEP3A_DERIVED_FIELD_MISSING_SOURCE: returns requires pct_chg/return source')
        return_values = pd.to_numeric(working[return_col], errors='coerce')
        if return_col == 'pct_chg':
            return_values = return_values / 100.0
        working['returns'] = return_values
        added.append('returns')
        sources['returns'] = return_col
        derived_fields['returns'] = _derived_alias_spec(
            'returns',
            [return_col],
            'pct_chg / 100' if return_col == 'pct_chg' else f'alias(returns <- {return_col})',
            'decimal_return',
        )
        if return_col == 'pct_chg':
            derived_fields['returns']['source_units'] = {'pct_chg': 'percent'}

    if needs_vwap and 'vwap' not in working.columns:
        volume_col = 'volume' if 'volume' in working.columns else 'vol' if 'vol' in working.columns else None
        if volume_col is None or 'amount' not in working.columns:
            raise SystemExit('BLOCK_FACTORFORGE_STEP3A_DERIVED_FIELD_MISSING_SOURCE: vwap requires amount and volume/vol source')
        volume = pd.to_numeric(working[volume_col], errors='coerce').replace(0, pd.NA)
        amount = pd.to_numeric(working['amount'], errors='coerce')
        working['vwap'] = amount / volume
        added.append('vwap')
        sources['vwap'] = f'amount/{volume_col}'
        derived_fields['vwap'] = _derived_alias_spec(
            'vwap',
            ['amount', volume_col],
            f'amount / {volume_col}',
            'price_proxy',
            operator='divide',
        )

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
            derived_fields[field] = _derived_alias_spec(
                field,
                [volume_col],
                f'rolling_mean({volume_col},{window})',
                'documented_volume_unit',
                operator='mean',
                lookback_window=window,
            )

    source_fields = sorted(
        field
        for field in required
        if field in working.columns and field not in derived_fields and field not in added
    )
    derived_fields.update(formula_operator_contract_specs(formula_ir))

    return working, {
        'version': 'factorforge_derived_field_contract_v1',
        'validation_result': 'PASS',
        'standard_formula_fields_added': added,
        'standard_formula_field_sources': sources,
        'required_formula_fields': sorted(required),
        'source_fields': source_fields,
        'derived_fields': derived_fields,
        'report_local_only': True,
        'clean_data_mutation': False,
    }


def materialize_shared_daily_slice(
    report_id: str,
    sample_window: dict,
    symbols: list[str] | None = None,
    csv_output_policy: str | None = None,
    required_fields: list[str] | None = None,
    formula_ir: dict | None = None,
) -> dict:
    del symbols
    local_dir = RUNS / report_id / 'step3a_local_inputs'
    local_dir.mkdir(parents=True, exist_ok=True)
    needs_cross_sectional_sample = requires_cross_sectional_sample(formula_ir)
    step3_sample_universe: str | list[str] = 'a_share_all' if needs_cross_sectional_sample else ['000001.SZ', '000002.SZ']
    daily_fields = select_clean_daily_fields_for_formula(required_fields, formula_ir)
    daily_basic_fields = select_daily_basic_fields_for_required_formula_fields(required_fields)
    daily_basic_required = len(daily_basic_fields) > 2
    full_query_window = data_api_window_bounds(sample_window)
    executability_window = step3a_executability_window(sample_window, formula_ir=formula_ir)
    query_window = data_api_window_bounds(executability_window)
    daily_resolution = resolve_data_api_dataset(
        'clean_daily_bar',
        start=query_window['start'],
        end=query_window['end'],
        fields=daily_fields,
        universe=step3_sample_universe,
    )
    daily_basic_resolution = None
    if daily_basic_required:
        daily_basic_resolution = resolve_data_api_dataset(
            'daily_basic',
            start=query_window['start'],
            end=query_window['end'],
            fields=daily_basic_fields,
            universe=step3_sample_universe,
        )
    step4_data_contract = build_step4_data_contract(
        sample_window=sample_window,
        daily_resolution=daily_resolution,
        daily_basic_resolution=daily_basic_resolution,
        daily_fields=daily_fields,
        daily_basic_fields=daily_basic_fields if daily_basic_required else None,
    )

    daily_basic_ready = (not daily_basic_required) or (
        isinstance(daily_basic_resolution, dict) and daily_basic_resolution.get('status') in {'ready', 'proxy_ready'}
    )
    if daily_resolution.get('status') != 'ready' or not daily_basic_ready:
        return {
            'snapshot_note': (
                'Data API could not resolve ready clean_daily_bar/daily_basic. Factor Forge Step3A only consumes '
                'published clean data products; publish or sync the Data API catalog before Step3A.'
            ),
            'snapshot_source': 'missing_data_api_clean_daily_bar',
            'input_mode': 'daily_only',
            'data_api_resolution': {'clean_daily_bar': daily_resolution, 'daily_basic': daily_basic_resolution},
            'step4_data_contract': step4_data_contract,
        }

    daily_result = fetch_data_api_dataset(
        'clean_daily_bar',
        start=query_window['start'],
        end=query_window['end'],
        fields=daily_fields,
        universe=step3_sample_universe,
        frequency='daily',
        catalog_path=daily_resolution.get('catalog_path'),
    )
    daily_basic_result = None
    if daily_basic_required and daily_basic_resolution:
        daily_basic_result = fetch_data_api_dataset(
            'daily_basic',
            start=query_window['start'],
            end=query_window['end'],
            fields=daily_basic_fields,
            universe=step3_sample_universe,
            catalog_path=daily_basic_resolution.get('catalog_path'),
        )
    daily_basic_fetch_ready = (not daily_basic_required) or (
        daily_basic_result is not None and daily_basic_result.status in {'ready', 'proxy_ready'}
    )
    if daily_result.status not in {'ready', 'proxy_ready'} or not daily_basic_fetch_ready:
        return {
            'snapshot_note': (
                'Data API resolved clean_daily_bar/daily_basic metadata but failed to fetch the report-local daily snapshot.'
            ),
            'snapshot_source': 'missing_data_api_clean_daily_bar',
            'input_mode': 'daily_only',
            'data_api_resolution': {
                'clean_daily_bar': daily_result.to_metadata(),
                'daily_basic': daily_basic_result.to_metadata() if daily_basic_result is not None else daily_basic_resolution,
            },
            'step4_data_contract': step4_data_contract,
        }

    daily_df = daily_result.frame.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    if daily_basic_result is not None:
        daily_basic_df = daily_basic_result.frame.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
        overlap = [
            col for col in daily_basic_df.columns
            if col in daily_df.columns and col not in {'ts_code', 'trade_date'}
        ]
        if overlap:
            daily_basic_df = daily_basic_df.drop(columns=overlap)
        daily_df = daily_df.merge(daily_basic_df, on=['ts_code', 'trade_date'], how='left')
    cross_sectional_sample_contract = None
    if needs_cross_sectional_sample:
        ticker_counts = daily_df.groupby('trade_date')['ts_code'].nunique() if not daily_df.empty else pd.Series(dtype='int64')
        min_tickers_per_day = int(ticker_counts.min()) if not ticker_counts.empty else 0
        median_tickers_per_day = float(ticker_counts.median()) if not ticker_counts.empty else 0.0
        cross_sectional_sample_contract = {
            'version': 'factorforge_step3a_cross_sectional_sample_contract_v1',
            'required_by_operator': 'cross_sectional_operator',
            'operator_set': sorted(set(formula_ir.get('operator_set') or []) if isinstance(formula_ir, dict) else []),
            'sample_universe': 'a_share_all',
            'min_tickers_per_day': min_tickers_per_day,
            'median_tickers_per_day': median_tickers_per_day,
            'date_count': int(ticker_counts.shape[0]),
            'validation_result': 'PASS' if min_tickers_per_day >= 3 else 'BLOCK',
            'minimum_required_tickers_per_day': 3,
        }
        if min_tickers_per_day < 3:
            return {
                'sample_window_actual': executability_window,
                'step4_full_window': full_query_window,
                'snapshot_note': 'Step3A could not build a valid cross-sectional sample for Formula-IR cross-sectional executability proof.',
                'snapshot_source': 'data_api_clean_daily_bar',
                'input_mode': 'blocked_cross_sectional_sample',
                'data_api_resolution': {'clean_daily_bar': daily_result.to_metadata()},
                'step4_data_contract': step4_data_contract,
                'cross_sectional_sample_contract': cross_sectional_sample_contract,
            }
    daily_df, derived_field_contract = enrich_report_local_daily_fields(
        daily_df,
        required_fields or [],
        formula_ir=formula_ir,
    )
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
        'sample_window_actual': executability_window,
        'step4_full_window': full_query_window,
        'snapshot_note': 'Step3A resolved clean_daily_bar through Data API and wrote a bounded report-local daily snapshot for Step3B executability proof; Step4 owns full formal data execution.',
        'snapshot_source': 'data_api_clean_daily_bar',
        'input_mode': 'daily_only',
        'daily_df_parquet': str(daily_parquet.relative_to(WORKSPACE)),
        'preferred_daily_format': 'parquet',
        **audit_payload,
        'data_api_resolution': {'clean_daily_bar': daily_resolution, 'daily_basic': daily_basic_resolution},
        'step4_data_contract': step4_data_contract,
        'daily_filter_policy': daily_resolution.get('daily_filter_policy'),
        'daily_filter_summary': daily_resolution.get('coverage') or {},
        'derived_field_contract': derived_field_contract,
        'cross_sectional_sample_contract': cross_sectional_sample_contract,
    }


def materialize_moneyflow_slice(
    report_id: str,
    sample_window: dict,
    csv_output_policy: str | None = None,
    required_fields: list[str] | None = None,
) -> dict:
    local_dir = RUNS / report_id / 'step3a_local_inputs'
    local_dir.mkdir(parents=True, exist_ok=True)
    requested = list(dict.fromkeys(['ts_code', 'trade_date'] + list(required_fields or [])))
    fields = [field for field in requested if field in MONEYFLOW_DATASET_FIELDS]
    query_window = data_api_window_bounds(sample_window)
    moneyflow_resolution = resolve_data_api_dataset(
        'moneyflow',
        start=query_window['start'],
        end=query_window['end'],
        fields=fields,
    )
    clean_daily_fields = ['open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg']
    clean_daily_resolution = resolve_data_api_dataset(
        'clean_daily_bar',
        start=query_window['start'],
        end=query_window['end'],
        fields=clean_daily_fields,
    )
    step4_data_contract = build_step4_data_contract(
        sample_window=sample_window,
        daily_resolution=clean_daily_resolution,
        moneyflow_resolution=moneyflow_resolution,
        daily_fields=clean_daily_fields,
        moneyflow_fields=fields,
    )
    if moneyflow_resolution.get('status') != 'ready':
        return {
            'snapshot_note': 'Data API could not resolve ready moneyflow. Step3A will not proxy active buy/sell with OHLCV.',
            'snapshot_source': 'missing_data_api_moneyflow',
            'input_mode': 'daily_only',
            'data_api_resolution': {'moneyflow': moneyflow_resolution},
            'step4_data_contract': step4_data_contract,
        }

    moneyflow_result = fetch_data_api_dataset(
        'moneyflow',
        start=query_window['start'],
        end=query_window['end'],
        fields=fields,
        universe='a_share_all',
        frequency='daily',
        catalog_path=moneyflow_resolution.get('catalog_path'),
    )
    if moneyflow_result.status not in {'ready', 'proxy_ready'}:
        return {
            'snapshot_note': 'Data API resolved moneyflow metadata but failed to fetch the report-local moneyflow snapshot.',
            'snapshot_source': 'missing_data_api_moneyflow',
            'input_mode': 'daily_only',
            'data_api_resolution': {'moneyflow': moneyflow_result.to_metadata()},
            'step4_data_contract': step4_data_contract,
        }

    moneyflow_df = moneyflow_result.frame.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    policy = resolve_csv_policy(csv_output_policy)
    moneyflow_parquet = local_dir / f'daily_input__{report_id}.parquet'
    moneyflow_csv = local_dir / f'daily_input__{report_id}.csv'
    moneyflow_sample_csv = local_dir / f'daily_input_sample__{report_id}.csv'
    moneyflow_df.to_parquet(moneyflow_parquet, index=False)
    audit_payload = materialize_daily_audit_csv(
        moneyflow_df,
        report_id=report_id,
        full_csv_path=moneyflow_csv,
        sample_csv_path=moneyflow_sample_csv,
        policy=policy,
    )
    return {
        'sample_window_actual': {
            'start': str(moneyflow_df['trade_date'].min()) if len(moneyflow_df) else query_window['start'],
            'end': str(moneyflow_df['trade_date'].max()) if len(moneyflow_df) else query_window['end'],
        },
        'snapshot_note': 'Step3A resolved moneyflow through Data API and wrote a report-local moneyflow daily panel for Step3B sample proof.',
        'snapshot_source': 'data_api_moneyflow',
        'input_mode': 'daily_only',
        'daily_df_parquet': str(moneyflow_parquet.relative_to(WORKSPACE)),
        'preferred_daily_format': 'parquet',
        **audit_payload,
        'data_api_resolution': {'moneyflow': moneyflow_resolution},
        'step4_data_contract': step4_data_contract,
        'derived_field_contract': {
            'version': 'factorforge_derived_field_contract_v1',
            'validation_result': 'PASS',
            'standard_formula_fields_added': [],
            'standard_formula_field_sources': {},
            'required_formula_fields': sorted(fields),
            'source_fields': sorted(fields),
            'derived_fields': {},
            'report_local_only': True,
            'clean_data_mutation': False,
        },
    }


def build_local_price_volume_snapshots(
    report_id: str,
    sample_window: dict,
    csv_output_policy: str | None = None,
    required_fields: list[str] | None = None,
    formula_ir: dict | None = None,
):
    local_dir = RUNS / report_id / 'step3a_local_inputs'
    local_dir.mkdir(parents=True, exist_ok=True)
    step3_sample_universe = ['000001.SZ', '000002.SZ']
    daily_fields = select_clean_daily_fields_for_formula(required_fields, formula_ir)
    minute_fields = ['open', 'high', 'low', 'close', 'vol', 'amount']
    daily_basic_fields = select_daily_basic_fields_for_required_formula_fields(required_fields)
    daily_basic_required = len(daily_basic_fields) > 2
    full_query_window = data_api_window_bounds(sample_window)
    executability_window = step3a_executability_window(sample_window, formula_ir=formula_ir)
    query_window = data_api_window_bounds(executability_window)
    minute_derived_requirement = minute_derived_flow_state_requirement(
        start_date=full_query_window['start'],
        end_date=research_window_contract(sample_window)['in_sample']['end'],
        cutoff_time=DEFAULT_MINUTE_DERIVED_CUTOFF_TIME,
        source_data_version=os.getenv('FACTORFORGE_MINUTE_SOURCE_DATA_VERSION') or 'minute_bar_raw_v1',
    )
    daily_resolution = resolve_data_api_dataset(
        'clean_daily_bar',
        start=query_window['start'],
        end=query_window['end'],
        fields=daily_fields,
        universe=step3_sample_universe,
    )
    minute_resolution = resolve_data_api_dataset(
        'minute_bar',
        start=query_window['start'],
        end=query_window['end'],
        fields=minute_fields,
        universe=step3_sample_universe,
        frequency='1min',
    )
    daily_basic_resolution = None
    if daily_basic_required:
        daily_basic_resolution = resolve_data_api_dataset(
            'daily_basic',
            start=query_window['start'],
            end=query_window['end'],
            fields=daily_basic_fields,
            universe=step3_sample_universe,
        )
    step4_data_contract = build_step4_data_contract(
        sample_window=sample_window,
        daily_resolution=daily_resolution,
        minute_resolution=minute_resolution,
        daily_basic_resolution=daily_basic_resolution,
        daily_fields=daily_fields,
        minute_fields=minute_fields,
        daily_basic_fields=daily_basic_fields if daily_basic_required else None,
        minute_derived_state_requirements=[minute_derived_requirement],
    )
    daily_basic_ready = (not daily_basic_required) or (
        isinstance(daily_basic_resolution, dict) and daily_basic_resolution.get('status') in {'ready', 'proxy_ready'}
    )
    if daily_resolution.get('status') != 'ready' or minute_resolution.get('status') not in {'ready', 'proxy_ready'} or not daily_basic_ready:
        return {
            'snapshot_note': 'Data API could not resolve required minute/daily/daily_basic datasets; Step3A will not guess raw minute paths or build clean layers.',
            'snapshot_source': 'missing_data_api_minute_or_daily',
            'input_mode': 'price_volume_minute',
            'data_api_resolution': {
                'clean_daily_bar': daily_resolution,
                'minute_bar': minute_resolution,
                'daily_basic': daily_basic_resolution,
            },
            'step4_data_contract': step4_data_contract,
        }
    daily_result = fetch_data_api_dataset(
        'clean_daily_bar',
        start=query_window['start'],
        end=query_window['end'],
        fields=daily_fields,
        universe=step3_sample_universe,
        catalog_path=daily_resolution.get('catalog_path'),
    )
    minute_result = fetch_data_api_dataset(
        'minute_bar',
        start=query_window['start'],
        end=query_window['end'],
        fields=minute_fields,
        universe=step3_sample_universe,
        frequency='1min',
        catalog_path=minute_resolution.get('catalog_path'),
    )
    daily_basic_result = None
    if daily_basic_required and daily_basic_resolution:
        daily_basic_result = fetch_data_api_dataset(
            'daily_basic',
            start=query_window['start'],
            end=query_window['end'],
            fields=daily_basic_fields,
            universe=step3_sample_universe,
            catalog_path=daily_basic_resolution.get('catalog_path'),
        )
    daily_basic_fetch_ready = (not daily_basic_required) or (
        daily_basic_result is not None and daily_basic_result.status in {'ready', 'proxy_ready'}
    )
    if daily_result.status != 'ready' or minute_result.status not in {'ready', 'proxy_ready'} or not daily_basic_fetch_ready:
        return {
            'snapshot_note': 'Data API resolved minute/daily metadata but failed to fetch the Step3B sample snapshots.',
            'snapshot_source': 'missing_data_api_minute_or_daily',
            'input_mode': 'price_volume_minute',
            'data_api_resolution': {
                'clean_daily_bar': daily_result.to_metadata(),
                'minute_bar': minute_result.to_metadata(),
                'daily_basic': daily_basic_result.to_metadata() if daily_basic_result is not None else daily_basic_resolution,
            },
            'step4_data_contract': step4_data_contract,
        }
    daily_df = daily_result.frame.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    if daily_basic_result is not None:
        daily_basic_df = daily_basic_result.frame.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
        overlap = [
            col for col in daily_basic_df.columns
            if col in daily_df.columns and col not in {'ts_code', 'trade_date'}
        ]
        if overlap:
            daily_basic_df = daily_basic_df.drop(columns=overlap)
        daily_df = daily_df.merge(daily_basic_df, on=['ts_code', 'trade_date'], how='left')
    minute_sort = [col for col in ['ts_code', 'trade_date', 'trade_time'] if col in minute_result.frame.columns]
    minute_df = minute_result.frame.sort_values(minute_sort).reset_index(drop=True) if minute_sort else minute_result.frame.reset_index(drop=True)
    daily_parquet = local_dir / f'daily_input__{report_id}.parquet'
    daily_csv = local_dir / f'daily_input__{report_id}.csv'
    daily_sample_csv = local_dir / f'daily_input_sample__{report_id}.csv'
    minute_parquet = local_dir / f'minute_input__{report_id}.parquet'
    minute_csv = local_dir / f'minute_input__{report_id}.csv'
    minute_sample_csv = local_dir / f'minute_input_sample__{report_id}.csv'
    daily_df.to_parquet(daily_parquet, index=False)
    minute_df.to_parquet(minute_parquet, index=False)
    daily_audit = materialize_daily_audit_csv(
        daily_df,
        report_id=report_id,
        full_csv_path=daily_csv,
        sample_csv_path=daily_sample_csv,
        policy=resolve_csv_policy(csv_output_policy),
    )
    minute_csv_profile = materialize_daily_audit_csv(
        minute_df,
        report_id=report_id,
        full_csv_path=minute_csv,
        sample_csv_path=minute_sample_csv,
        policy=resolve_csv_policy(csv_output_policy),
    )
    return {
        'sample_window_actual': sample_window,
        'step3b_executability_window_actual': executability_window,
        'snapshot_note': 'Step3A resolved minute_bar and clean_daily_bar through Data API and wrote report-local sample snapshots for Step3B executability proof; Step4 owns full data execution.',
        'snapshot_source': 'data_api_minute_plus_daily',
        'input_mode': 'price_volume_minute',
        'daily_df_path': str(daily_parquet.relative_to(WORKSPACE)),
        'daily_df_parquet': str(daily_parquet.relative_to(WORKSPACE)),
        'minute_df_path': str(minute_parquet.relative_to(WORKSPACE)),
        'minute_df_parquet': str(minute_parquet.relative_to(WORKSPACE)),
        'minute_df_csv': minute_csv_profile.get('daily_df_csv'),
        'minute_df_csv_sample': minute_csv_profile.get('daily_df_csv_sample'),
        **daily_audit,
        'minute_io_contract': minute_csv_profile.get('daily_io_contract'),
        'data_api_resolution': {
            'clean_daily_bar': daily_resolution,
            'minute_bar': minute_resolution,
            'daily_basic': daily_basic_resolution,
        },
        'step4_data_contract': step4_data_contract,
        'step4_full_window': full_query_window,
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
            daily_slice = materialize_shared_daily_slice(
                report_id,
                sample_window,
                symbols=tickers,
                required_fields=required_fields,
                formula_ir=formula_ir,
            )
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
    daily_df, derived_field_contract = enrich_report_local_daily_fields(
        daily_df,
        required_fields or [],
        formula_ir=formula_ir,
    )

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
        'derived_field_contract': derived_field_contract,
    }


def build_local_daily_snapshot(
    report_id: str,
    sample_window: dict,
    csv_output_policy: str | None = None,
    required_fields: list[str] | None = None,
    formula_ir: dict | None = None,
):
    # Daily-only factors resolve the published clean_daily_bar Data API contract.
    return materialize_shared_daily_slice(
        report_id,
        sample_window,
        csv_output_policy=csv_output_policy,
        required_fields=required_fields,
        formula_ir=formula_ir,
    )


def materialize_retained_chip_state_slice(
    report_id: str,
    sample_window: dict,
    csv_output_policy: str | None = None,
):
    local_dir = RUNS / report_id / 'step3a_local_inputs'
    local_dir.mkdir(parents=True, exist_ok=True)
    step3_sample_universe = ['000001.SZ', '000002.SZ']
    daily_fields = ['open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg']
    full_query_window = data_api_window_bounds(sample_window)
    executability_window = step3a_executability_window(sample_window, formula_ir=formula_ir)
    query_window = data_api_window_bounds(executability_window)

    daily_resolution = resolve_data_api_dataset(
        'clean_daily_bar',
        start=query_window['start'],
        end=query_window['end'],
        fields=daily_fields,
        universe=step3_sample_universe,
    )
    minute_resolution = resolve_data_api_dataset(
        'minute_bar',
        start=query_window['start'],
        end=query_window['end'],
        fields=['ts_code', 'trade_date', 'trade_time'],
        universe=step3_sample_universe,
        frequency='1min',
    )
    state_resolution = resolve_data_api_dataset(
        INTRADAY_RETAINED_CHIP_STATE_DATASET,
        start=query_window['start'],
        end=query_window['end'],
        fields=RETAINED_CHIP_STATE_FIELDS,
        universe=step3_sample_universe,
        frequency='daily',
    )
    formal_scope = str(os.getenv('FACTORFORGE_RETAINED_CHIP_FORMAL_SCOPE') or 'oos').strip().lower()
    state_freshness = state_resolution.get('freshness') if isinstance(state_resolution.get('freshness'), dict) else {}
    formal_end = _normalize_window_date(state_freshness.get('trade_date_max')) or '20260612'
    formal_window = {
        'start': '20160104' if formal_scope == 'full' else '20250714',
        'end': formal_end,
        'scope': 'full_is_plus_oos' if formal_scope == 'full' else 'oos_targeted_holdout',
    }
    state_requirement = retained_chip_state_requirement(
        start_date=formal_window['start'],
        end_date=formal_window['end'],
        catalog_path=state_resolution.get('catalog_path'),
    )
    step4_data_contract = build_step4_data_contract(
        sample_window=sample_window,
        daily_resolution=daily_resolution,
        minute_resolution=minute_resolution,
        daily_fields=daily_fields,
        minute_fields=['ts_code', 'trade_date', 'trade_time'],
        minute_derived_state_requirements=[state_requirement],
    )
    daily_full_query = step4_data_contract.get('full_queries', {}).get('clean_daily_bar')
    if isinstance(daily_full_query, dict):
        daily_full_query['dataset'] = 'clean_daily_bar_oos_slice' if formal_window['scope'] == 'oos_targeted_holdout' else 'clean_daily_bar'
        daily_full_query['start_date'] = formal_window['start']
        daily_full_query['end_date'] = formal_window['end']
    minute_full_query = step4_data_contract.get('full_queries', {}).get('minute_bar')
    if isinstance(minute_full_query, dict):
        minute_full_query['start_date'] = formal_window['start']
        minute_full_query['end_date'] = formal_window['end']
    step4_data_contract['formal_query_window'] = formal_window
    step4_data_contract['research_window_contract'] = {
        'version': 'factorforge_research_window_contract_v1',
        'default_in_sample_end': '2025-07-11',
        'in_sample': {
            'start': '2016-01-04',
            'end': '2025-07-11',
            'status': 'not_run_in_oos_targeted_contract' if formal_window['scope'] == 'oos_targeted_holdout' else 'included',
        },
        'oos': {
            'start': '2025-07-14',
            'end': formal_window['end'],
            'policy': 'holdout_only_no_revision_fitting',
            'run_scope': formal_window['scope'],
        },
        'revision_fitting_policy': 'Step5/Step6 may diagnose OOS but must not repeatedly fit revisions on OOS evidence.',
    }
    if daily_resolution.get('status') != 'ready' or state_resolution.get('status') not in {'ready', 'proxy_ready'}:
        return {
            'snapshot_note': 'Data API could not resolve clean_daily_bar or intraday_retained_chip_state_v1; Step3A will not fall back to raw minute_bar.',
            'snapshot_source': 'missing_data_api_retained_chip_state',
            'input_mode': 'retained_chip_state',
            'data_api_resolution': {
                'clean_daily_bar': daily_resolution,
                INTRADAY_RETAINED_CHIP_STATE_DATASET: state_resolution,
                'minute_bar': minute_resolution,
            },
            'step4_data_contract': step4_data_contract,
        }

    # Step3B is an executability proof, not alpha evidence.  The retained-chip
    # datamart is S3-partitioned and can be slow to schema-open on Mac; avoid
    # letting a bounded proof scan remote partitions.  Formal Step4 still owns
    # the real Data API datamart read through step4_data_contract.
    smoke_dates = [query_window['start']]
    if query_window['end'] != query_window['start']:
        smoke_dates.append(query_window['end'])
    daily_rows = []
    state_rows = []
    for date_idx, trade_date in enumerate(smoke_dates):
        for ticker_idx, ts_code in enumerate(step3_sample_universe):
            base = 10.0 + date_idx + ticker_idx * 0.5
            daily_rows.append({
                'ts_code': ts_code,
                'trade_date': trade_date,
                'open': base,
                'high': base * 1.01,
                'low': base * 0.99,
                'close': base * 1.005,
                'vol': 100000.0 + 1000.0 * ticker_idx,
                'volume': 100000.0 + 1000.0 * ticker_idx,
                'amount': 10000000.0 + 100000.0 * date_idx,
                'pct_chg': 0.5 + 0.1 * ticker_idx,
            })
            amount_sum = 200000000.0 + 1000000.0 * date_idx
            lcr_raw = 0.35 + 0.05 * ticker_idx + 0.02 * date_idx
            state_rows.append({
                'ts_code': ts_code,
                'trade_date': trade_date,
                'lcr_raw': lcr_raw,
                'retained_amount_sum': amount_sum * lcr_raw,
                'amount_sum_20d': amount_sum,
                'interval_turnover_sum_20d': 1.2 + 0.1 * ticker_idx,
                'survival_weighted_interval_count': 40.0 + date_idx,
                'interval_count': 80,
                'valid_interval_count': 80,
                'lookback_days': 20,
                'interval_minutes': 15,
                'turnover_denominator_source': 'float_share',
                'float_share': 1000000000.0,
                'float_share_unit': 'share',
                'amount_unit': 'CNY',
                'source_min_date': smoke_dates[0],
                'source_max_date': trade_date,
                'missing_interval_count': 0,
                'turnover_clipped_count': 0,
                'qa_status': 'PASS',
            })

    daily_df = pd.DataFrame(daily_rows).sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    state_df = pd.DataFrame(state_rows).sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    daily_parquet = local_dir / f'daily_input__{report_id}.parquet'
    daily_csv = local_dir / f'daily_input__{report_id}.csv'
    daily_sample_csv = local_dir / f'daily_input_sample__{report_id}.csv'
    state_parquet = local_dir / f'retained_chip_state_input__{report_id}.parquet'
    state_csv = local_dir / f'retained_chip_state_input__{report_id}.csv'
    state_sample_csv = local_dir / f'retained_chip_state_input_sample__{report_id}.csv'
    daily_df.to_parquet(daily_parquet, index=False)
    state_df.to_parquet(state_parquet, index=False)
    daily_audit = materialize_daily_audit_csv(
        daily_df,
        report_id=report_id,
        full_csv_path=daily_csv,
        sample_csv_path=daily_sample_csv,
        policy=resolve_csv_policy(csv_output_policy),
    )
    state_csv_profile = materialize_daily_audit_csv(
        state_df,
        report_id=report_id,
        full_csv_path=state_csv,
        sample_csv_path=state_sample_csv,
        policy=resolve_csv_policy(csv_output_policy),
    )
    return {
        'sample_window_actual': sample_window,
        'step3b_executability_window_actual': executability_window,
        'snapshot_note': 'Step3A resolved intraday_retained_chip_state_v1 and clean_daily_bar metadata through Data API; Step3B uses a deterministic schema-smoke sample while Step4 owns the real S3 datamart read.',
        'snapshot_source': 'data_api_retained_chip_state_schema_smoke',
        'input_mode': 'price_volume_minute',
        'formula_input_dataset': INTRADAY_RETAINED_CHIP_STATE_DATASET,
        'sample_is_synthetic_schema_smoke': True,
        'sample_alpha_evidence_allowed': False,
        'derived_field_contract': {
            'version': 'factorforge_derived_field_contract_v1',
            'report_local_only': True,
            'clean_data_mutation': False,
            'validation_result': 'PASS',
            'source_fields': [
                'ts_code',
                'trade_date',
                'trade_time',
                'amount',
                'vol',
                'volume',
                'free_float_shares_or_float_shares',
                'minute_turnover_rate',
                'interval_15m_turnover_rate',
                'interval_15m_amount',
                'retained_amount',
                'cumulative_retained_amount',
                'cumulative_amount',
            ],
            'standard_formula_fields_added': [],
            'derived_fields': {
                'factor_value': {
                    'operator': 'direct_code_state_adapter',
                    'sources': ['lcr_raw'],
                    'source_units': {'lcr_raw': 'ratio'},
                    'output_unit': 'ratio',
                    'rule': 'factor_value = lcr_raw from intraday_retained_chip_state_v1',
                    'leakage_policy': 'no future data',
                },
            },
            'state_dataset': INTRADAY_RETAINED_CHIP_STATE_DATASET,
            'state_semantics': 'raw minute and 15-minute turnover/amount inputs are pre-aggregated into retained-chip state upstream; Step3B schema-smoke sample does not mutate clean data.',
        },
        'daily_df_path': str(daily_parquet.relative_to(WORKSPACE)),
        'daily_df_parquet': str(daily_parquet.relative_to(WORKSPACE)),
        'minute_df_path': str(state_parquet.relative_to(WORKSPACE)),
        'minute_df_parquet': str(state_parquet.relative_to(WORKSPACE)),
        'minute_df_csv': state_csv_profile.get('daily_df_csv'),
        'minute_df_csv_sample': state_csv_profile.get('daily_df_csv_sample'),
        **daily_audit,
        'minute_io_contract': state_csv_profile.get('daily_io_contract'),
        'data_api_resolution': {
            'clean_daily_bar': daily_resolution,
            INTRADAY_RETAINED_CHIP_STATE_DATASET: state_resolution,
            'minute_bar': minute_resolution,
        },
        'step4_data_contract': step4_data_contract,
        'step4_full_window': full_query_window,
        'daily_filter_policy': daily_resolution.get('daily_filter_policy'),
        'daily_filter_summary': daily_resolution.get('coverage') or {},
    }


def build_step3a(report_id: str, csv_output_policy: str | None = None):
    fsm = load_json(OBJ / 'factor_spec_master' / f'factor_spec_master__{report_id}.json')
    _aim = load_json(OBJ / 'alpha_idea_master' / f'alpha_idea_master__{report_id}.json')
    handoff_to_step3 = read_existing_json(OBJ / 'handoff' / f'handoff_to_step3__{report_id}.json')

    factor_id = fsm.get('factor_id', report_id)
    canonical = fsm.get('canonical_spec', {})
    formula_ir = canonical.get('formula_ir') if isinstance(canonical.get('formula_ir'), dict) else {}
    required_fields = formula_required_daily_fields(fsm)
    moneyflow_fields = moneyflow_required_fields(fsm)
    need_moneyflow = bool(moneyflow_fields)
    retained_chip_state = direct_code_uses_retained_chip_state(fsm)
    price_volume_minute = is_price_volume_minute_formula(canonical)
    direct_code_minute = (not retained_chip_state) and direct_code_requires_minute_inputs(fsm)
    required = canonical.get('required_inputs', [])
    required_text = ' '.join(required)
    need_minute = (not need_moneyflow) and (not retained_chip_state) and (bool(re.search(r'minute|分钟|高频', required_text, re.I)) or price_volume_minute or direct_code_minute)
    need_daily = not need_moneyflow
    need_daily_basic = price_volume_minute or bool(re.search(r'market_cap|total_mv|circ_mv|turnover|pe|pb|ps|估值|市值', required_text, re.I))
    explicitly_required_intraday_proxy_datasets = [
        dataset_id for dataset_id in INTRADAY_PROXY_DATASETS
        if dataset_id in required or dataset_id in required_text
    ]
    missing_intraday_proxy_datasets = []
    intraday_proxy_catalog_path = None
    for dataset_id in explicitly_required_intraday_proxy_datasets:
        registered, catalog_path = data_api_dataset_registered(dataset_id)
        intraday_proxy_catalog_path = intraday_proxy_catalog_path or catalog_path
        if not registered:
            missing_intraday_proxy_datasets.append(dataset_id)
    if missing_intraday_proxy_datasets:
        need_minute = False
        need_daily = False
        need_moneyflow = False
        need_daily_basic = False

    sample_window = declared_sample_window(fsm, handoff_to_step3, infer_sample_window(factor_id, required_text))
    data_sources = []
    coverage = []
    proxy_rules = []
    blocked = []
    field_mapping = {}
    notes = []
    intraday_proxy_blocked_local_input_paths = None

    if missing_intraday_proxy_datasets:
        data_sources.extend([
            {
                'name': dataset_id,
                'kind': 'data_api_catalog_dataset',
                'path': None,
                'fields': [],
                'normalized_dataset': dataset_id,
            }
            for dataset_id in explicitly_required_intraday_proxy_datasets
        ])
        coverage.append({
            'name': 'intraday_flow_proxy_catalog',
            'status': 'blocked',
            'detail': (
                'Step2 explicitly requires intraday proxy dataset(s), but they are not registered in the Data API catalog: '
                + ', '.join(missing_intraday_proxy_datasets)
            ),
            'catalog_path': intraday_proxy_catalog_path,
        })
        field_mapping.update({
            'instrument': 'ts_code',
            'date': 'trade_date',
            'intraday_cutoff': 'trade_time',
            'active_flow_proxy': 'net_active_flow_proxy_1450',
            'flow_concentration': 'flow_hhi_1450',
            'impact_efficiency': 'price_impact_efficiency_1450',
        })
        blocked.append({
            'code': 'DATA_API_INTRADAY_FLOW_PROXY_DATASET_UNAVAILABLE',
            'detail': (
                'Required clean/precomputed intraday proxy dataset is absent from the Data API catalog. '
                'Step3A must not fall back to raw minute_bar downloads for this formal hypothesis.'
            ),
            'missing_datasets': missing_intraday_proxy_datasets,
            'catalog_path': intraday_proxy_catalog_path,
        })
        intraday_proxy_blocked_local_input_paths = {
            'input_mode': 'blocked',
            'snapshot_source': 'missing_intraday_flow_proxy_dataset',
            'snapshot_note': (
                'Step3A blocked before raw minute fetch because the factor requires clean/precomputed '
                'intraday flow proxy datasets not present in the Data API catalog.'
            ),
            'missing_datasets': missing_intraday_proxy_datasets,
            'catalog_path': intraday_proxy_catalog_path,
            'data_api_resolution': {
                'status': 'dataset_missing',
                'missing_datasets': missing_intraday_proxy_datasets,
                'catalog_path': intraday_proxy_catalog_path,
            },
            'step4_data_contract': {
                'status': 'blocked',
                'reason': 'missing_intraday_flow_proxy_dataset',
                'required_datasets': explicitly_required_intraday_proxy_datasets,
                'forbidden_fallback': 'raw minute_bar fetch',
            },
        }

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

    if need_moneyflow:
        data_sources.append({
            'name': 'tushare_moneyflow',
            'kind': 's3_partitioned',
            'path': 's3://yufan-data-lake/tushares/资金流向数据/个股资金流向/',
            'fields': moneyflow_fields,
            'normalized_dataset': 'moneyflow',
        })
        coverage.append({'name': 'moneyflow_catalog', 'status': 'pending', 'detail': 'Data API catalog must resolve moneyflow for the declared sample window'})
        field_mapping.update({
            'instrument': 'ts_code',
            'date': 'trade_date',
            'buy_sm_amount': 'buy_sm_amount',
            'sell_sm_amount': 'sell_sm_amount',
            'buy_md_amount': 'buy_md_amount',
            'sell_md_amount': 'sell_md_amount',
            'buy_lg_amount': 'buy_lg_amount',
            'sell_lg_amount': 'sell_lg_amount',
            'buy_elg_amount': 'buy_elg_amount',
            'sell_elg_amount': 'sell_elg_amount',
            'net_mf_amount': 'net_mf_amount',
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
    if intraday_proxy_blocked_local_input_paths is not None:
        local_input_paths = intraday_proxy_blocked_local_input_paths
        notes.append(str(local_input_paths.get('snapshot_note') or ''))
    elif retained_chip_state:
        local_input_paths = materialize_retained_chip_state_slice(
            report_id,
            sample_window,
            csv_output_policy=csv_output_policy,
        )
        snapshot_note = local_input_paths.get('snapshot_note')
        snapshot_source = local_input_paths.get('snapshot_source')
        data_sources.append({
            'name': INTRADAY_RETAINED_CHIP_STATE_DATASET,
            'kind': 'data_api_catalog_dataset',
            'path': 's3://yufan-data-lake/factorforge/datamart/intraday_retained_chip_state/v1/',
            'fields': RETAINED_CHIP_STATE_FIELDS,
            'normalized_dataset': INTRADAY_RETAINED_CHIP_STATE_DATASET,
        })
        coverage.append({
            'name': INTRADAY_RETAINED_CHIP_STATE_DATASET,
            'status': 'blocked' if snapshot_source == 'missing_data_api_retained_chip_state' else 'pass',
            'detail': snapshot_note,
        })
        field_mapping.update({
            'instrument': 'ts_code',
            'date': 'trade_date',
            'retained_chip_ratio_lcr': 'lcr_raw',
            'retained_amount': 'retained_amount_sum',
            'total_amount_20d': 'amount_sum_20d',
        })
        notes.append('LCR uses the accepted intraday_retained_chip_state_v1 datamart; Step3A must not fetch raw minute_bar for retained-chip reconstruction.')
        if snapshot_note:
            notes.append(str(snapshot_note))
        if snapshot_source == 'missing_data_api_retained_chip_state':
            blocked.append({
                'code': 'DATA_API_RETAINED_CHIP_STATE_UNAVAILABLE',
                'detail': snapshot_note,
            })
    elif need_moneyflow:
        local_input_paths = materialize_moneyflow_slice(
            report_id,
            sample_window,
            csv_output_policy=csv_output_policy,
            required_fields=moneyflow_fields,
        )
        snapshot_note = local_input_paths.get('snapshot_note')
        snapshot_source = local_input_paths.get('snapshot_source')
        if snapshot_note:
            notes.append(str(snapshot_note))
        if snapshot_source == 'data_api_moneyflow':
            notes.append('Step 3A 已生成 moneyflow Data API contract；Step3B 只允许小样本 executability proof，Step4 负责全量正式数据执行')
            coverage = [
                item if item.get('name') != 'moneyflow_catalog' else {
                    **item,
                    'status': 'pass',
                    'detail': 'moneyflow resolved through Data API catalog',
                }
                for item in coverage
            ]
        elif snapshot_source == 'missing_data_api_moneyflow':
            blocked.append({
                'code': 'DATA_API_MONEYFLOW_UNAVAILABLE',
                'detail': snapshot_note,
            })
    elif need_minute:
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
        local_input_paths = build_local_price_volume_snapshots(
            report_id,
            sample_window,
            csv_output_policy=csv_output_policy,
            required_fields=required_fields,
            formula_ir=formula_ir,
        )
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
            formula_ir=formula_ir,
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
        'minute_derived_state_requirements': (local_input_paths.get('step4_data_contract') or {}).get('minute_derived_state_requirements') or [],
        'research_window_contract': (local_input_paths.get('step4_data_contract') or {}).get('research_window_contract') or research_window_contract(sample_window),
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
        'research_window_contract': (local_input_paths.get('step4_data_contract') or {}).get('research_window_contract') or research_window_contract(sample_window),
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
    maybe_reexec_from_step3_template_copy(args.report_id, args.manifest)
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
