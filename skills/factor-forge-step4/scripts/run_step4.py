#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import hashlib
import inspect
import importlib.util
import json
import math
import os
import shlex
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

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
FACTORFORGE = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
WORKSPACE = FACTORFORGE.parent
OBJ = FACTORFORGE / 'objects'
RUNS = FACTORFORGE / 'runs'

from factor_factory.data_access import build_forward_return_frame, infer_signal_column, normalize_trade_date_series
from factor_factory.data_access.minute_derived import (
    DEFAULT_MINUTE_CUTOFF_TIME,
    FLOW_STATE_REQUIRED_COLUMNS,
MINUTE_DERIVED_FLOW_STATE_V1,
    load_flow_state_partitions,
    normalize_cutoff_time,
    normalize_trade_date,
    research_window_contract as default_research_window_contract,
)
from factor_factory.data_api import fetch_data_api_dataset
from factor_factory.runtime_context import (
    load_runtime_manifest,
    manifest_factorforge_root,
    manifest_path,
    manifest_report_id,
)

PLACEHOLDER_TOKENS = {'', 'TODO', 'TBD', 'PLACEHOLDER', 'placeholder', 'todo', 'tbd', None}
TRADE_DATE_FETCH_STATE_DATASETS = {'intraday_retained_chip_state_v1'}

STEP4_RUN_METADATA_OWNED_FIELDS = {
    'report_id',
    'factor_id',
    'implementation_mode_decision',
    'implementation_path',
    'started_at_utc',
    'finished_at_utc',
    'row_count',
    'date_count',
    'ticker_count',
    'signal_column',
    'actual_window',
    'target_window',
    'effective_target_window',
    'run_status_candidate',
    'input_io_profile',
    'step4_factor_io_profile',
    'step4_formal_factor_identity',
    'step4_factor_csv_policy_observed',
    'shared_evaluation_context',
    'backend_timing_profile',
    'research_window_contract',
}
FACTOR_CSV_POLICY_VALUES = {'full_csv', 'sample_csv', 'no_csv'}


def derive_identity(parent: dict[str, Any], role: str, producer: str = 'step4') -> dict[str, Any]:
    identity = dict(parent or {})
    identity['artifact_role'] = role
    identity['producer'] = producer
    return identity


def enforce_direct_step_policy(manifest_path_arg: str | None = None) -> None:
    global FACTORFORGE, WORKSPACE, OBJ, RUNS
    if os.getenv('FACTORFORGE_ULTIMATE_RUN') == '1':
        return
    if os.getenv('FACTORFORGE_ALLOW_DIRECT_STEP') != '1':
        raise SystemExit(
            'BLOCKED_DIRECT_STEP: formal Step4 execution must enter via scripts/run_factorforge_ultimate.py. '
            'Direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.'
        )
    debug_raw = os.getenv('FACTORFORGE_DEBUG_ROOT')
    if not debug_raw:
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    debug_root = Path(debug_raw).expanduser().resolve()
    if not debug_root.exists():
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    canonical_root = FACTORFORGE.expanduser().resolve()
    if debug_root == canonical_root:
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    if manifest_path_arg:
        manifest = load_runtime_manifest(manifest_path_arg)
        if manifest_factorforge_root(manifest).expanduser().resolve() != debug_root:
            raise SystemExit('BLOCKED_DIRECT_STEP: direct debug manifest must point to FACTORFORGE_DEBUG_ROOT.')
    FACTORFORGE = debug_root
    WORKSPACE = FACTORFORGE.parent
    OBJ = FACTORFORGE / 'objects'
    RUNS = FACTORFORGE / 'runs'
    os.environ['FACTORFORGE_ROOT'] = str(debug_root)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {path}')


def stable_json_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')).hexdigest()


def universe_hash_from_frame(frame: Any) -> str | None:
    if frame is None or 'ts_code' not in frame.columns:
        return None
    values = sorted(str(value) for value in frame['ts_code'].dropna().unique())
    return stable_json_hash(values)


def factor_key_hash_from_frame(frame: Any) -> str | None:
    if frame is None or not {'ts_code', 'trade_date'}.issubset(frame.columns):
        return None
    normalized_dates = normalize_trade_date_series(frame['trade_date']).dt.strftime('%Y%m%d')
    keys = [
        [str(code), str(date)]
        for code, date in zip(frame['ts_code'].astype(str).tolist(), normalized_dates.tolist(), strict=False)
    ]
    return stable_json_hash(keys)


def factor_artifact_binding_profile(path: Path, frame: Any) -> dict[str, Any]:
    return {
        'selected_factor_sha256': sha256_file(path),
        'selected_factor_row_count': int(len(frame)) if frame is not None else 0,
        'selected_factor_schema': [str(col) for col in frame.columns] if frame is not None else [],
        'selected_factor_key_hash': factor_key_hash_from_frame(frame),
    }


def merge_run_metadata(existing_meta: dict[str, Any], step4_owned_fields: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(existing_meta or {})
    for key, value in step4_owned_fields.items():
        if key not in STEP4_RUN_METADATA_OWNED_FIELDS:
            raise ValueError(f'Step4 attempted to overwrite non-owned run metadata field: {key}')
        metadata[key] = value
    return metadata


def step4_factor_csv_policy_from_step3b(existing_meta: dict[str, Any]) -> dict[str, Any]:
    csv_profile = ((existing_meta or {}).get('performance_profile') or {}).get('csv_output_profile') or {}
    raw_policy = csv_profile.get('csv_output_policy')
    if raw_policy is None:
        env_policy = (os.getenv('FACTORFORGE_CSV_OUTPUT_POLICY') or '').strip()
        if env_policy:
            policy = str(env_policy)
            if policy not in FACTOR_CSV_POLICY_VALUES:
                raise SystemExit(f'BLOCK_STEP4_INVALID_FACTOR_CSV_POLICY:{policy}')
            allowed = policy == 'full_csv'
            written = allowed
            reason = None if allowed else f'step4_env_{policy}_policy'
            source = 'step4_env'
        else:
            policy = 'legacy_missing'
            allowed = True
            written = True
            reason = None
            source = 'legacy_missing'
    else:
        policy = str(raw_policy)
        if policy not in FACTOR_CSV_POLICY_VALUES:
            raise SystemExit(f'BLOCK_STEP4_INVALID_FACTOR_CSV_POLICY:{policy}')
        allowed = policy == 'full_csv'
        written = allowed
        reason = None if allowed else f'step3b_{policy}_policy'
        source = 'step3b_run_metadata'
    return {
        'source': source,
        'csv_output_policy': policy,
        'factor_csv_write_allowed': bool(allowed),
        'factor_csv_written_by_step4': bool(written),
        'factor_csv_write_skipped_reason': reason,
    }


def classify_existing_factor_parquet_source(existing_meta: dict[str, Any]) -> dict[str, Any]:
    prior_step4_profile = (existing_meta or {}).get('step4_factor_io_profile') or {}
    if prior_step4_profile.get('source') == 'step4_recompute_fallback' or prior_step4_profile.get('recomputed_factor') is True:
        return {
            'source': 'prior_step4_parquet',
            'upstream_recomputed_factor': True,
            'provenance_basis': 'run_metadata.step4_factor_io_profile',
        }

    performance_profile = (existing_meta or {}).get('performance_profile') or {}
    producer = (existing_meta or {}).get('producer')
    if (
        performance_profile.get('version') == 'factorforge_step3b_performance_profile_v1'
        or producer in {'step3b', 'step3b_first_run', 'step3b_sample_proof'}
        or prior_step4_profile.get('source') == 'step3b_factor_parquet'
    ):
        return {
            'source': 'step3b_sample_or_legacy_factor_parquet',
            'upstream_recomputed_factor': False,
            'provenance_basis': 'run_metadata.step3b_profile',
        }

    return {
        'source': 'existing_factor_parquet_unknown_provenance',
        'upstream_recomputed_factor': None,
        'provenance_basis': 'run_metadata.missing_or_unrecognized',
    }



def _frame_key_stats(df: Any) -> dict[str, Any]:
    if df is None or not {'ts_code', 'trade_date'}.issubset(df.columns):
        return {
            'row_count': int(len(df)) if df is not None else 0,
            'date_count': None,
            'ticker_count': None,
            'start': None,
            'end': None,
        }
    # Step4 already consumes normalized daily snapshots. Avoid expensive
    # full-column datetime formatting here; identity stats only need YYYYMMDD.
    normalized_dates = df['trade_date'].astype(str).str.replace('-', '', regex=False).str.slice(0, 8)
    return {
        'row_count': int(len(df)),
        'date_count': int(normalized_dates.nunique()),
        'ticker_count': int(df['ts_code'].nunique()),
        'start': str(normalized_dates.min()),
        'end': str(normalized_dates.max()),
    }


def build_step4_reuse_identity(
    *,
    report_id: str,
    factor_id: str | None,
    base_identity: dict[str, Any],
    dpm: dict[str, Any],
    daily_df: Any,
) -> dict[str, Any]:
    stats = _frame_key_stats(daily_df)
    return {
        'producer': 'step4_formal_compute',
        'is_formal_factor_values': True,
        'report_id': report_id,
        'factor_id': factor_id,
        'implementation_mode': base_identity.get('implementation_mode'),
        'spec_hash': base_identity.get('spec_hash'),
        'formula_hash': base_identity.get('formula_hash'),
        'code_hash': base_identity.get('code_hash'),
        'data_catalog_hash': stable_json_hash({
            'local_input_paths': dpm.get('local_input_paths') or {},
            'data_sources': dpm.get('data_sources') or [],
            'field_mapping': dpm.get('field_mapping') or {},
        }),
        'data_api_contract_version': 'factorforge_step4_data_contract_v1',
        'window': {'start': stats.get('start'), 'end': stats.get('end')},
        'universe_hash': universe_hash_from_frame(daily_df),
        'frequency': 'daily',
    }


def fill_runtime_implementation_identity(base_identity: dict[str, Any], fsm: dict[str, Any], impl_path: Path) -> dict[str, Any]:
    effective = dict(base_identity or {})
    effective['code_hash'] = (
        effective.get('code_hash')
        or effective.get('code_contract_hash')
        or sha256_file(impl_path)
    )
    canonical = fsm.get('canonical_spec') if isinstance(fsm.get('canonical_spec'), dict) else {}
    implementation_contract = fsm.get('implementation_contract') if isinstance(fsm.get('implementation_contract'), dict) else {}
    effective['formula_hash'] = (
        effective.get('formula_hash')
        or fsm.get('formula_hash')
        or canonical.get('formula_hash')
        or implementation_contract.get('formula_hash')
    )
    return effective


def evaluate_reuse_gate(source_identity: dict[str, Any], expected_identity: dict[str, Any], *, source_artifact: str | None) -> dict[str, Any]:
    required = [
        'report_id',
        'factor_id',
        'implementation_mode',
        'spec_hash',
        'data_catalog_hash',
        'data_api_contract_version',
        'universe_hash',
        'frequency',
    ]
    source_window = source_identity.get('window') if isinstance(source_identity.get('window'), dict) else {}
    expected_window = expected_identity.get('window') if isinstance(expected_identity.get('window'), dict) else {}
    comparable = [*required, 'window.start', 'window.end']
    implementation_mode = expected_identity.get('implementation_mode')
    if implementation_mode == 'operator':
        comparable.append('formula_hash')
    elif implementation_mode in {'direct_code', 'hybrid'}:
        comparable.append('code_hash')
    else:
        comparable.extend(['formula_hash', 'code_hash'])
    matched_fields: list[str] = []
    mismatched_fields: list[str] = []
    missing_fields: list[str] = []
    for field in comparable:
        if field == 'window.start':
            source_value = source_window.get('start')
            expected_value = expected_window.get('start')
        elif field == 'window.end':
            source_value = source_window.get('end')
            expected_value = expected_window.get('end')
        else:
            source_value = source_identity.get(field)
            expected_value = expected_identity.get(field)
        if source_value in {None, ''} or expected_value in {None, ''}:
            missing_fields.append(field)
        elif str(source_value) == str(expected_value):
            matched_fields.append(field)
        else:
            mismatched_fields.append(field)
    producer = source_identity.get('producer')
    if source_identity.get('is_formal_factor_values') is True and producer == 'step3b_sample_proof':
        decision = 'block_invalid_formal_reuse'
        reason = 'step3b_sample_proof_marked_formal'
    elif mismatched_fields or missing_fields:
        decision = 'recompute_required'
        reason = (mismatched_fields[0] if mismatched_fields else missing_fields[0])
    else:
        decision = 'reuse_allowed'
        reason = 'identity_match'
    return {
        'version': 'factorforge_reuse_gate_v1',
        'decision': decision,
        'matched_fields': matched_fields,
        'mismatched_fields': mismatched_fields,
        'missing_fields': missing_fields,
        'source_artifact': source_artifact,
        'reason': reason,
        'source_producer': producer,
        'source_is_formal_factor_values': source_identity.get('is_formal_factor_values'),
    }


def apply_artifact_binding_to_reuse_gate(gate: dict[str, Any] | None, source_identity: dict[str, Any], source_artifact: str | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    gate = dict(gate or {
        'version': 'factorforge_reuse_gate_v1',
        'decision': 'recompute_required',
        'matched_fields': [],
        'mismatched_fields': [],
        'missing_fields': [],
        'source_artifact': source_artifact,
        'reason': 'reuse_gate_missing',
    })
    required = [
        'selected_factor_sha256',
        'selected_factor_row_count',
        'selected_factor_schema',
        'selected_factor_key_hash',
    ]
    if not source_artifact:
        gate['decision'] = 'recompute_required'
        gate['reason'] = 'source_artifact_missing'
        gate.setdefault('missing_fields', []).append('source_artifact')
        return gate, None
    artifact_path = Path(source_artifact)
    if not artifact_path.exists():
        gate['decision'] = 'recompute_required'
        gate['reason'] = 'source_artifact_missing'
        gate.setdefault('missing_fields', []).append('source_artifact')
        return gate, None
    try:
        artifact_df = pd.read_parquet(artifact_path)
    except Exception as exc:
        gate['decision'] = 'recompute_required'
        gate['reason'] = 'source_artifact_read_failed'
        gate['artifact_binding_error'] = str(exc)
        return gate, None
    actual = factor_artifact_binding_profile(artifact_path, artifact_df)
    matched: list[str] = []
    missing: list[str] = []
    mismatched: list[str] = []
    def is_missing(value: Any) -> bool:
        return value is None or value == '' or value == []
    for field in required:
        expected_value = source_identity.get(field)
        actual_value = actual.get(field)
        if is_missing(expected_value) or is_missing(actual_value):
            missing.append(field)
        elif expected_value == actual_value:
            matched.append(field)
        else:
            mismatched.append(field)
    gate['artifact_binding'] = {
        'version': 'factorforge_factor_artifact_binding_v1',
        'actual': actual,
        'matched_fields': matched,
        'missing_fields': missing,
        'mismatched_fields': mismatched,
    }
    if missing or mismatched:
        gate['decision'] = 'recompute_required'
        gate['reason'] = (mismatched[0] if mismatched else missing[0])
        gate.setdefault('missing_fields', []).extend(field for field in missing if field not in gate.get('missing_fields', []))
        gate.setdefault('mismatched_fields', []).extend(field for field in mismatched if field not in gate.get('mismatched_fields', []))
    return gate, artifact_df if not missing and not mismatched else None


def classify_step3b_compute_cache_source(step3b_meta: dict[str, Any], daily_df: Any, impl_path: Path, expected_identity: dict[str, Any] | None = None, source_artifact: str | None = None) -> dict[str, Any]:
    if not step3b_meta:
        gate = evaluate_reuse_gate({}, expected_identity or {}, source_artifact=source_artifact) if expected_identity else None
        return {'source': 'no_step3b_compute_cache', 'reusable': False, 'reason': 'metadata_missing', 'reuse_gate': gate}
    if step3b_meta.get('producer') != 'step3b_sample_proof':
        gate = evaluate_reuse_gate(step3b_meta, expected_identity or {}, source_artifact=source_artifact) if expected_identity else None
        return {'source': 'step3b_compute_cache_rejected', 'reusable': False, 'reason': 'producer_not_step3b_sample_proof', 'reuse_gate': gate}
    if step3b_meta.get('is_formal_factor_values') is True:
        gate = evaluate_reuse_gate(step3b_meta, expected_identity or {}, source_artifact=source_artifact) if expected_identity else None
        return {'source': 'step3b_compute_cache_rejected', 'reusable': False, 'reason': 'unexpected_formal_step3b_owner', 'reuse_gate': gate}
    if expected_identity:
        gate = evaluate_reuse_gate(step3b_meta, expected_identity, source_artifact=source_artifact)
        if gate.get('decision') != 'reuse_allowed':
            return {'source': 'step3b_compute_cache_rejected', 'reusable': False, 'reason': gate.get('reason') or 'reuse_gate_rejected', 'reuse_gate': gate}
    else:
        gate = None
    gate, bound_artifact_df = apply_artifact_binding_to_reuse_gate(gate, step3b_meta, source_artifact)
    if gate.get('decision') != 'reuse_allowed':
        return {
            'source': 'step3b_compute_cache_rejected',
            'reusable': False,
            'reason': gate.get('reason') or 'artifact_binding_failed',
            'reuse_gate': gate,
        }
    meta_impl = step3b_meta.get('implementation_path')
    if meta_impl:
        try:
            if Path(str(meta_impl)).expanduser().resolve() != impl_path.expanduser().resolve():
                return {'source': 'step3b_compute_cache_rejected', 'reusable': False, 'reason': 'implementation_path_mismatch', 'reuse_gate': gate}
        except OSError:
            return {'source': 'step3b_compute_cache_rejected', 'reusable': False, 'reason': 'implementation_path_unresolvable', 'reuse_gate': gate}
    expected = _frame_key_stats(daily_df)
    actual_window = step3b_meta.get('actual_window') if isinstance(step3b_meta.get('actual_window'), dict) else {}
    if int(step3b_meta.get('row_count') or -1) != int(expected['row_count']):
        return {'source': 'step3b_compute_cache_rejected', 'reusable': False, 'reason': 'row_count_mismatch', 'expected': expected, 'reuse_gate': gate}
    if int(step3b_meta.get('date_count') or -1) != int(expected['date_count'] or -1):
        return {'source': 'step3b_compute_cache_rejected', 'reusable': False, 'reason': 'date_count_mismatch', 'expected': expected, 'reuse_gate': gate}
    if int(step3b_meta.get('ticker_count') or -1) != int(expected['ticker_count'] or -1):
        return {'source': 'step3b_compute_cache_rejected', 'reusable': False, 'reason': 'ticker_count_mismatch', 'expected': expected, 'reuse_gate': gate}
    if str(actual_window.get('start')) != str(expected['start']) or str(actual_window.get('end')) != str(expected['end']):
        return {
            'source': 'step3b_compute_cache_rejected',
            'reusable': False,
            'reason': 'window_mismatch',
            'expected': expected,
            'actual_window': actual_window,
            'reuse_gate': gate,
        }
    return {
        'source': 'step3b_full_compute_cache',
        'reusable': True,
        'upstream_recomputed_factor': True,
        'provenance_basis': 'step3b_sample_run_metadata_full_coverage',
        'expected': expected,
        'reuse_gate': gate or {
            'version': 'factorforge_reuse_gate_v1',
            'decision': 'reuse_allowed',
            'matched_fields': [],
            'mismatched_fields': [],
            'missing_fields': [],
            'source_artifact': source_artifact,
            'reason': 'legacy_count_window_match',
        },
    }

def output_paths_for_policy(parquet_path: Path, csv_path: Path, sample_csv_path: Path, meta_path: Path, policy_observed: dict[str, Any]) -> list[str]:
    paths = [str(parquet_path)]
    policy = policy_observed.get('csv_output_policy')
    if policy_observed.get('factor_csv_write_allowed'):
        paths.append(str(csv_path))
    elif policy == 'sample_csv' and sample_csv_path.exists():
        paths.append(str(sample_csv_path))
    paths.append(str(meta_path))
    return paths


def file_sizes_for_paths(paths: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for raw_path in paths:
        p = Path(raw_path)
        if p.exists():
            result[str(p)] = p.stat().st_size
    return result


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def shared_evaluation_context_enabled(cli_enabled: bool) -> bool:
    raw = os.getenv('FACTORFORGE_ENABLE_SHARED_EVALUATION_CONTEXT', '').strip().lower()
    return bool(cli_enabled or raw in {'1', 'true', 'yes', 'on'})


def artifact_contract(path: Path, df: Any) -> dict[str, Any]:
    return {
        'path': str(path),
        'sha256': sha256_file(path),
        'row_count': int(len(df)),
        'schema': [str(col) for col in df.columns],
    }


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def contains_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip() in PLACEHOLDER_TOKENS
    if isinstance(value, dict):
        return any(contains_placeholder(v) for v in value.values())
    if isinstance(value, list):
        return any(contains_placeholder(v) for v in value)
    try:
        return value in PLACEHOLDER_TOKENS
    except TypeError:
        return False


def file_info(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        'path': str(path),
        'size_bytes': stat.st_size,
        'mtime_utc': datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    }


def build_evaluation_plan(handoff: dict[str, Any]) -> dict[str, Any]:
    # COMMENT_POLICY: backend_extensibility
    # Evaluation plan is user-extensible via handoff_to_step4.evaluation_plan.
    # If absent, keep a visible default instead of hidden hard-code.
    plan = handoff.get('evaluation_plan') or {}
    backends = plan.get('backends') or [
        {'name': 'self_quant_analyzer', 'mode': 'quick'},
        {'name': 'qlib_backtest', 'mode': 'default'},
    ]
    return {
        'backends': backends,
        'metric_policy': plan.get('metric_policy', 'extensible')
    }


def build_backend_runs_stub(report_id: str, evaluation_plan: dict[str, Any], run_status: str) -> list[dict[str, Any]]:
    runs = []
    for item in evaluation_plan.get('backends', []):
        backend = item.get('name', 'unknown_backend')
        mode = item.get('mode', 'default')
        payload_dir = FACTORFORGE / 'evaluations' / report_id / backend
        payload_path = payload_dir / 'evaluation_payload.json'
        summary = {
            'mode': mode,
            'note': 'backend adapter placeholder; envelope is ready for self_quant / qlib / future evaluators'
        }
        status = 'skipped' if run_status == 'failed' else 'partial'
        runs.append({
            'backend': backend,
            'status': status,
            'summary': summary,
            'artifact_paths': [str(payload_path)] if status != 'skipped' else [],
            'payload_path': str(payload_path) if status != 'skipped' else None,
            'backend_config': item,
        })
    return runs


def current_repo_sha() -> str:
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=REPO_ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return 'unknown'


def _backend_status(backend_runs: list[dict[str, Any]], backend: str) -> str:
    item = next((run for run in backend_runs if run.get('backend') == backend or run.get('name') == backend), None)
    return str((item or {}).get('status') or 'not_attempted')


def qlib_native_status_from_backend_runs(backend_runs: list[dict[str, Any]], backend_timing_profile: dict[str, Any]) -> str:
    item = next((run for run in backend_runs if run.get('backend') == 'qlib_backtest' or run.get('name') == 'qlib_backtest'), None)
    if isinstance(item, dict):
        explicit_status = item.get('qlib_native_status')
        summary = item.get('summary') if isinstance(item.get('summary'), dict) else {}
        if explicit_status == 'not_applicable' or summary.get('qlib_native_status') == 'not_applicable':
            return 'not_applicable'
    qlib_status = str((item or {}).get('status') or 'not_attempted')
    timing = (backend_timing_profile.get('backends') or {}).get('qlib_native') or {}
    timing_status = str(timing.get('status') or '')
    if qlib_status == 'success':
        return 'native_backtest_success'
    if qlib_status == 'partial':
        return 'partial_payload'
    if qlib_status == 'failed':
        return 'failed'
    if qlib_status == 'skipped':
        if timing_status == 'ready':
            return 'preflight_ready'
        if timing_status:
            return 'preflight_blocked'
        return 'not_attempted'
    return 'not_attempted'


def reuse_gate_status_from_factor_io(step4_factor_io_profile: dict[str, Any]) -> str:
    if not isinstance(step4_factor_io_profile, dict) or not step4_factor_io_profile:
        return 'not_applicable'
    gate = step4_factor_io_profile.get('reuse_gate') if isinstance(step4_factor_io_profile.get('reuse_gate'), dict) else {}
    decision = str(gate.get('decision') or '')
    if step4_factor_io_profile.get('recomputed_factor') is True:
        return 'recomputed'
    if decision == 'reuse_allowed' or step4_factor_io_profile.get('recomputed_factor') is False:
        return 'reused'
    if decision.startswith('block_'):
        return 'blocked'
    return 'not_applicable'


def build_acceptance_summary(
    *,
    report_id: str,
    factor_id: str | None,
    run_status: str,
    output_paths: list[str],
    backend_runs: list[dict[str, Any]],
    backend_timing_profile: dict[str, Any],
    step4_factor_io_profile: dict[str, Any],
    input_io_profile: dict[str, Any],
) -> dict[str, Any]:
    factor_path = next((path for path in output_paths if str(path).endswith('.parquet')), None)
    return {
        'version': 'factorforge_production_acceptance_summary_v1',
        'report_id': report_id,
        'factor_id': factor_id,
        'run_id': f'{report_id}__run',
        'artifact_root': str(FACTORFORGE),
        'repo_sha': current_repo_sha(),
        'wrapper_status': 'PASS' if run_status in {'success', 'partial'} else 'FAIL',
        'validator_verdicts': {'step4': 'PENDING'},
        'step3b': {
            'backend': step4_factor_io_profile.get('source'),
            'input_format': input_io_profile.get('daily_selected_format'),
            'sample_only': step4_factor_io_profile.get('source') == 'step3b_compute_cache',
            'is_formal_factor_values': step4_factor_io_profile.get('source') == 'prior_step4_parquet',
            'phase_seconds': {},
            'formula_engine_profile': {},
            'parity_checked': True,
        },
        'step4': {
            'formal_factor_values_owner': 'Step4',
            'formal_factor_values_path': factor_path,
            'self_quant_status': _backend_status(backend_runs, 'self_quant_analyzer'),
            'qlib_native_status': qlib_native_status_from_backend_runs(backend_runs, backend_timing_profile),
            'phase_seconds': {},
        },
        'reuse': {
            'step3b_cache_reused_by_step4': step4_factor_io_profile.get('source') == 'step3b_compute_cache',
            'reuse_gate_status': reuse_gate_status_from_factor_io(step4_factor_io_profile),
            'reuse_reason': ((step4_factor_io_profile.get('reuse_gate') or {}).get('reason') if isinstance(step4_factor_io_profile.get('reuse_gate'), dict) else None),
        },
        'side_effects': {
            'clean_data_mutated': False,
            'generated_code_digest_changed': False,
            'official_record_written': False,
            'search_worker_started': False,
        },
        'metrics': {},
    }


def build_formal_signal_coverage_profile(
    *,
    result_df: Any,
    signal_col: str,
    actual_start: str | None,
    actual_end: str | None,
    effective_target_start: str | None,
    effective_target_end: str | None,
    min_non_null_coverage: float = 0.90,
    sparse_signal_allowed: bool = False,
) -> dict[str, Any]:
    row_count = int(len(result_df)) if result_df is not None else 0
    date_count = int(result_df['trade_date'].nunique()) if row_count and 'trade_date' in result_df.columns else 0
    if row_count <= 0 or signal_col not in result_df.columns:
        non_null = 0
        nonnull_date_count = 0
        nonnull_start = None
        nonnull_end = None
    else:
        mask = result_df[signal_col].notna()
        non_null = int(mask.sum())
        if 'trade_date' in result_df.columns and non_null:
            nonnull_dates = result_df.loc[mask, 'trade_date'].astype(str).str.replace('-', '', regex=False).str.slice(0, 8)
            nonnull_date_count = int(nonnull_dates.nunique())
            nonnull_start = str(nonnull_dates.min())
            nonnull_end = str(nonnull_dates.max())
        else:
            nonnull_date_count = 0
            nonnull_start = None
            nonnull_end = None
    coverage = float(non_null / row_count) if row_count else 0.0
    reasons: list[str] = []
    if not sparse_signal_allowed and coverage < min_non_null_coverage:
        reasons.append('factor_value_non_null_coverage_below_minimum')
    if not sparse_signal_allowed and non_null > 0 and actual_end and nonnull_end and str(nonnull_end) != str(actual_end):
        reasons.append('nonnull_signal_window_does_not_reach_actual_end')
    if not sparse_signal_allowed and non_null == 0:
        reasons.append('factor_value_all_null')
    verdict = 'PASS' if not reasons else 'BLOCK'
    return {
        'version': 'factorforge_formal_signal_coverage_v1',
        'signal_column': signal_col,
        'row_count': row_count,
        'date_count': date_count,
        'factor_value_non_null': non_null,
        'factor_value_non_null_coverage': coverage,
        'nonnull_date_count': nonnull_date_count,
        'nonnull_start': nonnull_start,
        'nonnull_end': nonnull_end,
        'actual_window': {'start': actual_start, 'end': actual_end},
        'effective_target_window': {'start': effective_target_start, 'end': effective_target_end},
        'min_non_null_coverage': min_non_null_coverage,
        'sparse_signal_allowed': bool(sparse_signal_allowed),
        'coverage_gate_verdict': verdict,
        'block_reasons': reasons,
    }


def add_formal_acceptance_envelope(
    payload: dict[str, Any],
    *,
    identity: dict[str, Any],
    run_status: str,
    acceptance_summary: dict[str, Any],
) -> dict[str, Any]:
    out = dict(payload)
    out['run_id'] = identity.get('run_id') or f"{payload.get('report_id')}__run"
    out['artifact_root'] = str(FACTORFORGE)
    out['producer'] = identity.get('producer') or 'step4'
    out['status'] = run_status
    out['verdict'] = 'PASS' if run_status in {'success', 'partial'} else 'FAIL'
    out['acceptance_summary'] = acceptance_summary
    return out


def runtime_python() -> Path:
    venv_python = WORKSPACE / '.venvs' / 'quant-research' / 'bin' / 'python'
    if venv_python.exists():
        return venv_python
    if sys.executable:
        return Path(sys.executable)
    return Path('/usr/bin/python3')


def backend_runtime_python(backend: str, backend_cfg: dict[str, Any]) -> Path:
    if backend == 'qlib_backtest':
        raw_env = backend_cfg.get('env') if isinstance(backend_cfg.get('env'), dict) else {}
        qlib_python = (
            backend_cfg.get('qlib_python')
            or backend_cfg.get('qlib_python_path')
            or raw_env.get('FACTORFORGE_QLIB_PYTHON')
            or os.getenv('FACTORFORGE_QLIB_PYTHON')
        )
        if qlib_python:
            return Path(str(qlib_python)).expanduser()
    return runtime_python()


def resolve_backend_script_path(raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    p = Path(raw_path)
    if p.is_absolute():
        return p

    # Accept either repo-relative path or short script name under step4/scripts.
    candidates = [
        REPO_ROOT / p,
        REPO_ROOT / 'skills' / 'factor-forge-step4' / 'scripts' / p,
        FACTORFORGE / p,
        FACTORFORGE / 'skills' / 'factor-forge-step4' / 'scripts' / p,
    ]
    for c in candidates:
        if c.exists():
            return c
    return REPO_ROOT / p


def run_backend_script(
    report_id: str,
    backend: str,
    script_path: Path,
    payload_path: Path,
    backend_cfg: dict[str, Any],
    manifest_path_arg: Path | None = None,
) -> tuple[int, str]:
    extra_args: list[str] = []
    raw_args = backend_cfg.get('args')
    if isinstance(raw_args, list):
        extra_args = [str(x) for x in raw_args]
    elif isinstance(raw_args, str):
        extra_args = shlex.split(raw_args)

    # Custom backends receive the same CLI envelope as built-in adapters.
    cmd = [
        str(backend_runtime_python(backend, backend_cfg)),
        str(script_path),
        '--report-id',
        report_id,
        '--output',
        str(payload_path),
        *extra_args,
    ]
    if manifest_path_arg is not None:
        cmd.extend(['--manifest', str(manifest_path_arg)])
    env = os.environ.copy()
    env['STEP4_BACKEND_NAME'] = backend
    if manifest_path_arg is not None:
        env['FACTORFORGE_RUNTIME_MANIFEST'] = str(manifest_path_arg)
        try:
            manifest = load_runtime_manifest(manifest_path_arg)
            env['FACTORFORGE_ROOT'] = str(manifest_factorforge_root(manifest))
        except Exception:
            pass
    raw_env = backend_cfg.get('env')
    if isinstance(raw_env, dict):
        for k, v in raw_env.items():
            env[str(k)] = str(v)
    provider_uri = backend_cfg.get('provider_uri') or backend_cfg.get('qlib_provider_uri')
    if provider_uri and 'QLIB_PROVIDER_URI' not in env:
        env['QLIB_PROVIDER_URI'] = str(provider_uri)

    result = subprocess.run(cmd, check=False, capture_output=True, text=True, env=env)
    if result.stdout:
        print(result.stdout, end='')
    if result.stderr:
        print(result.stderr, end='')
    return result.returncode, f'cmd={" ".join(cmd)}'


def _backend_timing_key(backend: str | None) -> str:
    if backend == 'qlib_backtest':
        return 'qlib_native'
    return str(backend or 'unknown_backend')


def _provider_uri_from_backend_config(backend_cfg: dict[str, Any]) -> str | None:
    direct = backend_cfg.get('provider_uri') or backend_cfg.get('qlib_provider_uri')
    if direct:
        return str(direct)
    raw_env = backend_cfg.get('env')
    if isinstance(raw_env, dict) and raw_env.get('QLIB_PROVIDER_URI'):
        return str(raw_env.get('QLIB_PROVIDER_URI'))
    if os.getenv('QLIB_PROVIDER_URI'):
        return str(os.getenv('QLIB_PROVIDER_URI'))
    return None


def _resolve_provider_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return (FACTORFORGE / path).resolve()


def _default_qlib_provider_candidates(report_id: str) -> list[Path]:
    return [
        Path('/home/ubuntu/.qlib/qlib_data/cn_data'),
        Path.home() / '.qlib' / 'qlib_data' / 'cn_data',
        RUNS / report_id / 'qlib_provider',
    ]


def preflight_qlib_native(report_id: str, backend_cfg: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    explicit_provider = _provider_uri_from_backend_config(backend_cfg)
    if explicit_provider:
        candidate_paths = [_resolve_provider_path(explicit_provider)]
    else:
        candidate_paths = _default_qlib_provider_candidates(report_id)

    provider_path = next((path for path in candidate_paths if path.exists()), None)
    provider_present = provider_path is not None
    qlib_import_checked = True
    qlib_import_ok: bool | None = None
    qlib_import_reason: str | None = None
    status = 'ready'
    reason = None

    qlib_python = backend_runtime_python('qlib_backtest', backend_cfg)
    check_code = (
        "import qlib; "
        "assert hasattr(qlib, 'init'), f'imported non-Microsoft qlib package without init: {getattr(qlib, \"__file__\", None)}'; "
        "from qlib.data import D"
    )
    try:
        result = subprocess.run([str(qlib_python), '-c', check_code], check=False, capture_output=True, text=True)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or '').strip()
            raise ImportError(detail or f'{qlib_python} returned {result.returncode}')
        qlib_import_ok = True
    except Exception as exc:  # pragma: no cover - environment-specific dependency guard
        qlib_import_ok = False
        qlib_import_reason = f'qlib import/config unavailable for native backend via {qlib_python}: {type(exc).__name__}: {exc}'

    if not provider_present:
        status = 'skipped_native_missing_provider'
        reason = 'no usable qlib provider uri exists for native qlib backend'
        if qlib_import_reason:
            reason = f'{reason}; {qlib_import_reason}'
    elif not qlib_import_ok:
        status = 'skipped_native_import_unavailable'
        reason = qlib_import_reason
    else:
        status = 'ready'
        reason = None

    elapsed = time.perf_counter() - started
    return {
        'version': 'factorforge_qlib_preflight_v1',
        'provider_uri_checked': True,
        'provider_uri_candidates': [str(path) for path in candidate_paths],
        'provider_uri': str(provider_path) if provider_path is not None else (str(candidate_paths[0]) if candidate_paths else None),
        'provider_present': bool(provider_present),
        'qlib_import_checked': qlib_import_checked,
        'qlib_python': str(qlib_python),
        'qlib_import_ok': qlib_import_ok,
        'native_attempted': False,
        'status': status,
        'preflight_seconds': elapsed,
        'reason': reason,
    }


def write_backend_payloads(
    report_id: str,
    backend_runs: list[dict[str, Any]],
    manifest_path_arg: Path | None = None,
    shared_context: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # Builtin adapters and custom adapters share one payload contract.
    updated: list[dict[str, Any]] = []
    timing_profile: dict[str, Any] = {
        'version': 'factorforge_step4_backend_timing_profile_v1',
        'backends': {},
    }
    for item in backend_runs:
        payload_path = item.get('payload_path')
        if not payload_path:
            updated.append(item)
            continue
        p = Path(payload_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        backend = item.get('backend')
        backend_cfg = dict(item.get('backend_config')) if isinstance(item.get('backend_config'), dict) else {}
        shared_context_path = ((shared_context or {}).get('paths') or {}).get('context_json')
        if shared_context_path:
            raw_env = dict(backend_cfg.get('env')) if isinstance(backend_cfg.get('env'), dict) else {}
            raw_env['FACTORFORGE_SHARED_EVALUATION_CONTEXT_PATH'] = str(shared_context_path)
            backend_cfg['env'] = raw_env
        if backend in {'self_quant_analyzer', 'qlib_backtest'}:
            script_name = 'self_quant_adapter.py' if backend == 'self_quant_analyzer' else 'qlib_backtest_adapter.py'
            adapter = REPO_ROOT / 'skills' / 'factor-forge-step4' / 'scripts' / script_name
            preflight: dict[str, Any] | None = None
            if backend == 'qlib_backtest':
                preflight = preflight_qlib_native(report_id, backend_cfg)
                if preflight.get('status') != 'ready':
                    preflight_status = 'preflight_blocked'
                    if preflight.get('status') == 'ready':
                        preflight_status = 'preflight_ready'
                    payload = {
                        'backend': backend,
                        'report_id': report_id,
                        'status': 'skipped',
                        'mode': backend_cfg.get('mode', 'native'),
                        'qlib_native_status': preflight_status,
                        'summary': {'reason': preflight.get('reason')},
                        'qlib_preflight': preflight,
                        'shared_evaluation_context': {
                            'available': bool(shared_context_path),
                            'used': False,
                            'source': shared_context_path,
                            'identity_validated': False,
                            'fallback_reason': 'qlib_native_skipped_missing_provider',
                        },
                        'producer': 'step4-qlib-preflight',
                    }
                    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
                    new_item = dict(item)
                    new_item['status'] = 'skipped'
                    new_item['summary'] = payload['summary']
                    new_item['artifact_paths'] = [str(p)]
                    new_item['payload_path'] = str(p)
                    timing_profile['backends']['qlib_native'] = {
                        'attempted': False,
                        'status': preflight.get('status'),
                        'preflight_seconds': preflight.get('preflight_seconds'),
                        'wall_seconds': 0.0,
                        'reason': preflight.get('reason'),
                    }
                    updated.append(new_item)
                    continue

            started = time.perf_counter()
            result, exec_note = run_backend_script(report_id, backend, adapter, p, backend_cfg, manifest_path_arg=manifest_path_arg)
            wall_seconds = time.perf_counter() - started
            new_item = dict(item)
            new_item['status'] = 'success' if result == 0 else 'failed'
            if not p.exists():
                payload = {
                    'backend': backend,
                    'status': new_item['status'],
                    'mode': backend_cfg.get('mode', 'builtin'),
                    'summary': {
                        'error': 'builtin backend did not write payload',
                        'exec_note': exec_note,
                        'returncode': result,
                    },
                    'producer': 'step4-builtin-fallback',
                }
                p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            if p.exists():
                payload = json.loads(p.read_text(encoding='utf-8'))
                payload_status = payload.get('status')
                if payload_status in {'success', 'partial', 'failed', 'skipped'}:
                    new_item['status'] = payload_status
                if backend == 'self_quant_analyzer':
                    new_item['summary'] = payload.get('ic_summary', payload)
                else:
                    new_item['summary'] = payload.get('native_backtest_metrics') or payload.get('stub_backtest_metrics', payload)
                    if preflight is not None:
                        payload.setdefault('qlib_preflight', {**preflight, 'native_attempted': True})
                        payload.setdefault('qlib_native_status', qlib_native_status_from_backend_runs([new_item], {'backends': {'qlib_native': {'status': preflight.get('status')}}}))
                        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            timing_entry = {
                'attempted': True,
                'status': new_item.get('status'),
                'wall_seconds': wall_seconds,
            }
            if preflight is not None:
                timing_entry['preflight_seconds'] = preflight.get('preflight_seconds')
            timing_profile['backends'][_backend_timing_key(backend)] = timing_entry
            updated.append(new_item)
            continue

        custom_script = resolve_backend_script_path(
            str(backend_cfg.get('script_path') or backend_cfg.get('adapter_script') or '').strip() or None
        )
        if custom_script is not None:
            # Non-builtin backends are first-class: execute script and trust payload contract.
            new_item = dict(item)
            started = time.perf_counter()
            rc, exec_note = run_backend_script(report_id, backend, custom_script, p, backend_cfg, manifest_path_arg=manifest_path_arg)
            wall_seconds = time.perf_counter() - started
            new_item['status'] = 'success' if rc == 0 else 'failed'
            if not p.exists():
                # Guardrail: never leave missing payload for downstream Step5 readers.
                payload = {
                    'backend': backend,
                    'status': new_item['status'],
                    'mode': backend_cfg.get('mode', 'custom'),
                    'summary': {'error': 'custom backend did not write payload', 'exec_note': exec_note},
                    'producer': 'step4-custom-hook',
                }
                p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            payload = json.loads(p.read_text(encoding='utf-8'))
            new_item['summary'] = payload.get('summary') or payload.get('metrics') or payload
            timing_profile['backends'][_backend_timing_key(backend)] = {
                'attempted': True,
                'status': new_item.get('status'),
                'wall_seconds': wall_seconds,
            }
            updated.append(new_item)
            continue

        payload = {
            'backend': backend,
            'status': item.get('status'),
            'summary': item.get('summary'),
            'producer': 'step4-envelope',
            'extensible_metrics': True
        }
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        timing_profile['backends'][_backend_timing_key(backend)] = {
            'attempted': False,
            'status': item.get('status'),
            'wall_seconds': 0.0,
        }
        updated.append(item)
    return updated, timing_profile


def build_shared_evaluation_context(
    *,
    report_id: str,
    factor_id: str | None,
    implementation_mode_decision: dict[str, Any],
    base_identity: dict[str, Any],
    run_dir: Path,
    factor_df: Any,
    daily_df: Any,
    signal_col: str,
    factor_parquet_path: Path,
    daily_input_path: Path,
    target_window: dict[str, Any],
    effective_target_window: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    factor_signal_path = run_dir / f'factor_signal__{report_id}.parquet'
    daily_forward_returns_path = run_dir / f'daily_forward_returns__{report_id}.parquet'
    merged_path = run_dir / f'merged_signal_return__{report_id}.parquet'
    context_path = run_dir / f'shared_evaluation_context__{report_id}.json'

    required_factor_cols = ['ts_code', 'trade_date', signal_col]
    factor_signal = factor_df[required_factor_cols].copy()
    factor_signal = factor_signal.rename(columns={'ts_code': 'code'}).copy()
    factor_signal['datetime'] = normalize_trade_date_series(factor_signal['trade_date'])

    required_daily_cols = ['ts_code', 'trade_date', 'close']
    missing_daily_cols = [col for col in required_daily_cols if col not in daily_df.columns]
    if missing_daily_cols:
        raise ValueError(f'shared evaluation context requires daily columns: {missing_daily_cols}')
    daily_forward = build_forward_return_frame(
        daily_df[[col for col in ['ts_code', 'trade_date', 'close', 'pct_chg'] if col in daily_df.columns]].rename(columns={'ts_code': 'code'}),
        instrument_col='code',
        date_col='trade_date',
        price_col='close',
        horizon=1,
    )
    merged = factor_signal[['datetime', 'trade_date', 'code', signal_col]].merge(
        daily_forward[['datetime', 'code', 'future_return_1d']],
        on=['datetime', 'code'],
        how='left',
    ).dropna(subset=[signal_col, 'future_return_1d'])

    factor_signal.to_parquet(factor_signal_path, index=False)
    daily_forward.to_parquet(daily_forward_returns_path, index=False)
    merged.to_parquet(merged_path, index=False)

    identity = {
        'report_id': report_id,
        'factor_id': factor_id,
        'signal_column': signal_col,
        'factor_values_hash': sha256_file(factor_parquet_path),
        'daily_input_hash': sha256_file(daily_input_path),
        'daily_input_path': str(daily_input_path),
        'label_policy': {
            'horizon': 'T+1',
            'return_type': 'simple',
            'price_field': 'close',
        },
        'target_window': target_window,
        'effective_target_window': effective_target_window,
    }
    context = {
        'version': 'factorforge_shared_evaluation_context_v1',
        'enabled': True,
        'report_id': report_id,
        'factor_id': factor_id,
        'implementation_mode': (
            implementation_mode_decision.get('implementation_mode')
            or implementation_mode_decision.get('mode')
            or 'unknown'
        ),
        'spec_hash': base_identity.get('spec_hash'),
        'code_hash': base_identity.get('code_hash') or base_identity.get('code_contract_hash'),
        **identity,
        'paths': {
            'context_json': str(context_path),
            'factor_signal_parquet': str(factor_signal_path),
            'daily_forward_returns_parquet': str(daily_forward_returns_path),
            'merged_signal_return_parquet': str(merged_path),
            'quantile_assignment_parquet': None,
        },
        'artifacts': {
            'factor_signal': artifact_contract(factor_signal_path, factor_signal),
            'daily_forward_returns': artifact_contract(daily_forward_returns_path, daily_forward),
            'merged_signal_return': artifact_contract(merged_path, merged),
        },
        'row_counts': {
            'factor_signal': int(len(factor_signal)),
            'daily_forward_returns': int(len(daily_forward)),
            'merged_signal_return': int(len(merged)),
        },
        'cache_hit': False,
        'invalidated_reason': None,
        'build_seconds': time.perf_counter() - started,
    }
    write_json(context_path, context)
    return context


def resolve_input_paths(report_id: str, manifest: dict[str, Any] | None = None) -> dict[str, Path]:
    if manifest:
        objects = manifest.get('objects') or {}
        paths = {
            'factor_spec_master': Path(objects['factor_spec_master']),
            'data_prep_master': Path(objects['data_prep_master']),
            'handoff_to_step4': Path(objects['handoff_to_step4']),
        }
        return paths
    return {
        'factor_spec_master': OBJ / 'factor_spec_master' / f'factor_spec_master__{report_id}.json',
        'data_prep_master': OBJ / 'data_prep_master' / f'data_prep_master__{report_id}.json',
        'handoff_to_step4': OBJ / 'handoff' / f'handoff_to_step4__{report_id}.json',
    }


def dataframe_columns(path: Path) -> list[str]:
    if path.suffix.lower() == '.parquet':
        try:
            import pyarrow.parquet as pq
            return list(pq.read_schema(path).names)
        except Exception:
            import pandas as pd
            return list(pd.read_parquet(path).head(0).columns)
    import pandas as pd
    return list(pd.read_csv(path, nrows=0).columns)


def resolve_declared_daily_input_path(dpm: dict[str, Any], handoff: dict[str, Any], input_paths: dict[str, Path]) -> Path | None:
    if input_paths.get('daily'):
        return Path(input_paths['daily'])
    local_inputs = handoff.get('local_input_paths') if isinstance(handoff.get('local_input_paths'), dict) else {}
    if not local_inputs:
        local_inputs = dpm.get('local_input_paths') if isinstance(dpm.get('local_input_paths'), dict) else {}
    raw = local_inputs.get('daily_df_parquet') or local_inputs.get('daily_df_csv')
    if not raw:
        return None
    path = Path(str(raw))
    return path if path.is_absolute() else WORKSPACE / path


def validate_inputs(report_id: str, fsm: dict[str, Any], dpm: dict[str, Any], handoff: dict[str, Any], input_paths: dict[str, Path]) -> tuple[list[dict[str, Any]], list[str]]:
    issues: list[dict[str, Any]] = []
    warnings: list[str] = []

    for name, path in input_paths.items():
        if not path.exists():
            issues.append({'severity': 'error', 'code': 'MISSING_INPUT', 'message': f'missing required input: {name}', 'evidence': {'path': str(path)}})

    if issues:
        return issues, warnings

    if fsm.get('report_id') != report_id:
        issues.append({'severity': 'error', 'code': 'FSM_REPORT_ID_MISMATCH', 'message': 'factor_spec_master.report_id mismatch', 'evidence': {'expected': report_id, 'actual': fsm.get('report_id')}})
    if dpm.get('report_id') != report_id:
        issues.append({'severity': 'error', 'code': 'DPM_REPORT_ID_MISMATCH', 'message': 'data_prep_master.report_id mismatch', 'evidence': {'expected': report_id, 'actual': dpm.get('report_id')}})
    if handoff.get('report_id') != report_id:
        issues.append({'severity': 'error', 'code': 'HANDOFF_REPORT_ID_MISMATCH', 'message': 'handoff_to_step4.report_id mismatch', 'evidence': {'expected': report_id, 'actual': handoff.get('report_id')}})

    factor_id = fsm.get('factor_id')
    if contains_placeholder(factor_id):
        issues.append({'severity': 'error', 'code': 'FACTOR_ID_INVALID', 'message': 'factor_id is missing or placeholder', 'evidence': {'factor_id': factor_id}})
    if dpm.get('factor_id') != factor_id:
        issues.append({'severity': 'error', 'code': 'FACTOR_ID_MISMATCH', 'message': 'data_prep_master.factor_id mismatch', 'evidence': {'fsm': factor_id, 'dpm': dpm.get('factor_id')}})

    sample_window = dpm.get('sample_window', {})
    if contains_placeholder(sample_window.get('start')) or contains_placeholder(sample_window.get('end')):
        issues.append({'severity': 'error', 'code': 'SAMPLE_WINDOW_INVALID', 'message': 'sample window missing start/end', 'evidence': {'sample_window': sample_window}})

    if contains_placeholder(dpm.get('field_mapping')):
        issues.append({'severity': 'error', 'code': 'FIELD_MAPPING_INVALID', 'message': 'field_mapping missing or contains placeholder', 'evidence': {'field_mapping': dpm.get('field_mapping')}})

    if not dpm.get('data_sources'):
        issues.append({'severity': 'error', 'code': 'DATA_SOURCES_MISSING', 'message': 'data_sources missing', 'evidence': {}})

    canonical = fsm.get('canonical_spec') if isinstance(fsm.get('canonical_spec'), dict) else {}
    standard_contract = fsm.get('standard_formula_fields_contract') or canonical.get('standard_formula_fields_contract')
    required_standard_fields = []
    if isinstance(standard_contract, dict):
        required_standard_fields = [
            str(field).strip()
            for field in (standard_contract.get('required_standard_formula_fields') or [])
            if str(field).strip()
        ]
    daily_input_path = resolve_declared_daily_input_path(dpm, handoff, input_paths)
    if required_standard_fields and daily_input_path and daily_input_path.exists():
        daily_columns = dataframe_columns(daily_input_path)
        missing_standard_fields = sorted(set(required_standard_fields) - set(daily_columns))
        if missing_standard_fields:
            issues.append({
                'severity': 'error',
                'code': 'BLOCK_STANDARD_FORMULA_DERIVED_FIELD_NOT_IN_SNAPSHOT',
                'message': 'Step4 formal input snapshot missing required standard formula fields',
                'evidence': {
                    'daily_path': str(daily_input_path),
                    'missing': missing_standard_fields,
                },
            })

    if fsm.get('human_review_required'):
        warnings.append('factor_spec_master indicates human_review_required=true; Step 4 proceeds under frozen-schema execution discipline.')

    ambiguities = fsm.get('ambiguities') or []
    if ambiguities:
        warnings.append(f'factor_spec_master ambiguities present: {len(ambiguities)} item(s); Step 4 will not invent missing semantics.')

    return issues, warnings


def resolve_implementation_path(handoff: dict[str, Any], fsm: dict[str, Any]) -> tuple[str | None, list[str]]:
    notes: list[str] = []
    path = handoff.get('factor_impl_ref') or handoff.get('factor_impl_stub_ref') or handoff.get('implementation_path')
    if path and not contains_placeholder(path):
        source = 'factor_impl_ref' if handoff.get('factor_impl_ref') else ('factor_impl_stub_ref' if handoff.get('factor_impl_stub_ref') else 'implementation_path')
        notes.append(f'implementation path resolved from handoff_to_step4:{source}')
        return path, notes

    canonical = fsm.get('canonical_spec', {})
    fallback = canonical.get('implementation_path') or fsm.get('implementation_path')
    if fallback and not contains_placeholder(fallback):
        notes.append('implementation path resolved from factor_spec_master fallback')
        return fallback, notes

    notes.append('implementation path missing in handoff_to_step4 and factor_spec_master fallback')
    return None, notes


def import_module_from_path(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot create import spec for {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def add_direct_code_alias_columns(df: Any) -> Any:
    if not hasattr(df, 'copy') or not hasattr(df, 'columns'):
        return df
    out = df.copy()
    if 'vol' in out.columns and 'volume' not in out.columns:
        out['volume'] = out['vol']
    if 'volume' in out.columns and 'vol' not in out.columns:
        out['vol'] = out['volume']
    if 'pct_chg' in out.columns and 'returns' not in out.columns:
        out['returns'] = pd.to_numeric(out['pct_chg'], errors='coerce') / 100.0
    if 'returns' in out.columns and 'return' not in out.columns:
        out['return'] = out['returns']
    if 'return' in out.columns and 'returns' not in out.columns:
        out['returns'] = out['return']
    if 'trade_time' in out.columns and 'datetime' not in out.columns:
        out['datetime'] = out['trade_time']
    if 'datetime' in out.columns and 'trade_time' not in out.columns:
        out['trade_time'] = out['datetime']
    return out


def direct_code_expects_polars(module: Any) -> bool:
    path = Path(getattr(module, '__file__', '') or '')
    try:
        text = path.read_text(encoding='utf-8')
    except OSError:
        text = ''
    polars_api_markers = [
        '.with_columns(',
        '.select(',
        '.lazy(',
        'pl.col(',
        'polars.col(',
    ]
    return any(marker in text for marker in polars_api_markers)


def maybe_polars_frame(df: Any, use_polars: bool) -> Any:
    if not use_polars:
        return df
    try:
        import polars as pl
    except ImportError as exc:
        raise SystemExit(f'BLOCK_STEP4_DIRECT_CODE_DEPENDENCY_MISSING: polars dependency missing: {exc}') from exc
    return pl.from_pandas(df)


def normalize_direct_code_result(result: Any) -> Any:
    if isinstance(result, pd.DataFrame):
        return result
    if hasattr(result, 'to_pandas') and callable(result.to_pandas):
        return result.to_pandas()
    if hasattr(result, 'to_dicts') and callable(result.to_dicts):
        return pd.DataFrame(result.to_dicts())
    return result


def compute_factor_with_contract(module: Any, daily_df: Any, minute_df: Any) -> Any:
    """Call factor implementations without assuming legacy argument order."""
    fn = getattr(module, 'compute_factor')
    daily_input = add_direct_code_alias_columns(daily_df)
    minute_input = add_direct_code_alias_columns(minute_df)
    use_polars = direct_code_expects_polars(module)
    daily_call_input = maybe_polars_frame(daily_input, use_polars)
    minute_call_input = maybe_polars_frame(minute_input, use_polars)
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        params = []
    positional = [
        p for p in params
        if p.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
    ]

    if len(positional) == 1:
        first = positional[0].name.lower()
        if 'daily' in first:
            return normalize_direct_code_result(fn(daily_call_input))
        if 'minute' in first or 'intraday' in first:
            return normalize_direct_code_result(fn(minute_call_input))
        return normalize_direct_code_result(fn(minute_call_input if not minute_input.empty else daily_call_input))

    try:
        return normalize_direct_code_result(fn(daily_df=daily_call_input, minute_df=minute_call_input))
    except TypeError:
        if positional:
            first = positional[0].name.lower()
            if 'minute' in first:
                return normalize_direct_code_result(fn(minute_call_input, daily_call_input))
        return normalize_direct_code_result(fn(daily_call_input, minute_call_input))


def _query_with_date(query: dict[str, Any], trade_date: str) -> dict[str, Any]:
    return {**query, 'start_date': trade_date, 'end_date': trade_date}


def _normal_date_text(series: pd.Series) -> pd.Series:
    return series.astype(str).str.replace('-', '', regex=False).str.slice(0, 8)


def _normal_date_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {'none', 'nan', 'nat'}:
        return None
    return text.replace('-', '')[:8]


def _batched(values: list[str], size: int) -> list[list[str]]:
    return [values[idx: idx + size] for idx in range(0, len(values), size)]


def _step4_time_key(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip()
    token = text.str.split().str[-1]
    digits = token.str.extract(r"(\d{1,2}:?\d{2}:?\d{2})", expand=False).fillna(token)
    digits = digits.astype(str).str.replace(":", "", regex=False)
    numeric = pd.to_numeric(digits.str[-6:], errors="coerce")
    short = pd.to_numeric(token.str.extract(r"(\d{3,4})$", expand=False), errors="coerce")
    return numeric.fillna(short * 100).fillna(0).astype(int)


def _z_by_trade_date(frame: pd.DataFrame, col: str) -> pd.Series:
    grouped = frame.groupby("trade_date", sort=False)[col]
    mean = grouped.transform("mean")
    std = grouped.transform("std").replace(0, np.nan)
    return ((frame[col] - mean) / std).replace([np.inf, -np.inf], np.nan)


def _local_minute_partition_roots() -> list[Path]:
    candidates = []
    if os.environ.get('FACTORFORGE_LOCAL_MINUTE_ROOT'):
        candidates.append(Path(os.environ['FACTORFORGE_LOCAL_MINUTE_ROOT']))
    if os.environ.get('FACTORFORGE_LOCAL_DATA_ROOT'):
        candidates.append(Path(os.environ['FACTORFORGE_LOCAL_DATA_ROOT']) / '分钟数据' / 'raw' / 'stk_mins_1min')
    if os.environ.get('FACTORFORGE_DATA_CACHE'):
        candidates.append(Path(os.environ['FACTORFORGE_DATA_CACHE']) / 's3_parquet' / 'minute_bar-raw_v1-0b2b836c57d763c6')
    candidates.append(Path('/home/ubuntu/factorforge_data_api_cache/s3_parquet/minute_bar-raw_v1-0b2b836c57d763c6'))
    candidates.append(Path('/home/ubuntu/.qlib/raw_tushare/分钟数据/raw/stk_mins_1min'))
    roots = []
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir() and candidate not in roots:
            roots.append(candidate)
    return roots


def _local_minute_partition_paths(
    dates: list[str],
) -> tuple[list[Path] | None, dict[str, Any] | None]:
    roots = _local_minute_partition_roots()
    if not roots:
        return None, None
    root_probes = []
    for root in roots:
        part_paths: list[Path] = []
        missing_dates: list[str] = []
        for date in dates:
            date_dir = root / f'trade_date={date}'
            parts = sorted(date_dir.glob('*.parquet'))
            if not parts:
                missing_dates.append(date)
                continue
            part_paths.extend(parts)
        if missing_dates:
            root_probes.append({
                'root': str(root),
                'status': 'missing_partition',
                'missing_dates_head': missing_dates[:10],
                'missing_date_count': len(missing_dates),
            })
            continue
        return part_paths, {
            'source': 'local_minute_partition_root',
            'root': str(root),
            'root_probe_count': len(root_probes) + 1,
            'prior_root_probes': root_probes,
            'partition_count': len(part_paths),
            'date_count': len(dates),
            'date_start': dates[0] if dates else None,
            'date_end': dates[-1] if dates else None,
        }
    return None, {
        'source': 'local_minute_partition_probe',
        'roots': [str(root) for root in roots],
        'status': 'missing_partition',
        'root_probes': root_probes,
    }


def _read_local_minute_partitions(
    dates: list[str],
    *,
    fields: list[str],
) -> tuple[pd.DataFrame | None, dict[str, Any] | None]:
    required = ['ts_code', 'trade_date', 'trade_time']
    columns = list(dict.fromkeys(required + [field for field in fields if field not in required]))
    part_paths, meta = _local_minute_partition_paths(dates)
    if part_paths is None:
        return None, meta
    frames = []
    for part in part_paths:
        try:
            frames.append(pd.read_parquet(part, columns=columns))
        except (KeyError, ValueError):
            frames.append(pd.read_parquet(part))
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)
    return frame, {**(meta or {}), 'row_count': int(len(frame))}


def _fetch_minute_frame_for_dates(
    minute_query: dict[str, Any],
    dates: list[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    fields = list(minute_query.get('fields') or ['open', 'high', 'low', 'close', 'vol', 'amount'])
    local_frame, local_meta = _read_local_minute_partitions(dates, fields=fields)
    if local_frame is not None:
        return local_frame, local_meta or {}
    batch_start, batch_end = dates[0], dates[-1]
    frame, meta = _fetch_contract_frame({**minute_query, 'start_date': batch_start, 'end_date': batch_end})
    if local_meta:
        meta = {**meta, 'local_partition_probe': local_meta}
    return frame, meta


def _aggregate_intraday_flow_daily(minute_df: pd.DataFrame) -> pd.DataFrame:
    minute = minute_df.copy()
    if 'trade_date' in minute.columns:
        minute['trade_date'] = _normal_date_text(minute['trade_date'])
    if 'trade_time' not in minute.columns and 'datetime' in minute.columns:
        minute['trade_time'] = minute['datetime']
    if 'trade_time' not in minute.columns:
        minute['trade_time'] = '145000'
    if 'open' not in minute.columns and 'close' in minute.columns:
        minute['open'] = minute['close']
    if 'amount' not in minute.columns and 'vol' in minute.columns:
        minute['amount'] = minute['vol']
    minute['hhmmss'] = _step4_time_key(minute['trade_time'])
    minute = minute[minute['hhmmss'] <= 145000].copy()
    for col in ['open', 'close', 'amount', 'vol']:
        if col in minute.columns:
            minute[col] = pd.to_numeric(minute[col], errors='coerce')
    minute = minute.dropna(subset=['ts_code', 'trade_date', 'open', 'close', 'amount'])
    minute = minute[(minute['open'] > 0) & (minute['amount'].abs() > 0)]
    if len(minute) == 0:
        return pd.DataFrame(columns=[
            'ts_code', 'trade_date', 'signed_amt_sum', 'gross_amt', 'amt_sq_sum',
            'abs_ret_sum', 'ret_std', 'minute_count',
        ])
    minute['bar_ret'] = minute['close'] / minute['open'] - 1.0
    minute['amt_abs'] = minute['amount'].abs()
    minute['signed_amt'] = np.sign(minute['bar_ret'].fillna(0.0)) * minute['amt_abs']
    minute['amt_sq'] = minute['amt_abs'] * minute['amt_abs']
    minute['abs_bar_ret'] = minute['bar_ret'].abs()
    return minute.groupby(['ts_code', 'trade_date'], sort=False).agg(
        signed_amt_sum=('signed_amt', 'sum'),
        gross_amt=('amt_abs', 'sum'),
        amt_sq_sum=('amt_sq', 'sum'),
        abs_ret_sum=('abs_bar_ret', 'sum'),
        ret_std=('bar_ret', 'std'),
        minute_count=('bar_ret', 'count'),
    ).reset_index()


def _collect_polars_lazy(lazy_frame: Any) -> Any:
    try:
        return lazy_frame.collect(engine='streaming')
    except TypeError:
        try:
            return lazy_frame.collect(streaming=True)
        except TypeError:
            return lazy_frame.collect()


def _aggregate_intraday_flow_daily_polars_for_dates(
    dates: list[str],
) -> tuple[pd.DataFrame | None, dict[str, Any] | None]:
    part_paths, meta = _local_minute_partition_paths(dates)
    if part_paths is None:
        return None, meta
    try:
        import polars as pl
    except ImportError:
        return None, {**(meta or {}), 'status': 'polars_unavailable'}

    started = time.perf_counter()
    path_texts = [str(path) for path in part_paths]
    lf = pl.scan_parquet(path_texts, hive_partitioning=True)
    schema_names = set(lf.collect_schema().names())
    if 'ts_code' not in schema_names or 'close' not in schema_names:
        return None, {**(meta or {}), 'status': 'polars_schema_missing_core', 'columns': sorted(schema_names)}
    if 'trade_date' not in schema_names:
        return None, {**(meta or {}), 'status': 'polars_schema_missing_trade_date', 'columns': sorted(schema_names)}
    open_expr = pl.col('open') if 'open' in schema_names else pl.col('close')
    amount_expr = pl.col('amount') if 'amount' in schema_names else pl.col('vol')
    time_expr = pl.col('trade_time') if 'trade_time' in schema_names else (
        pl.col('datetime') if 'datetime' in schema_names else pl.lit('145000')
    )
    time_text = pl.col('_trade_time').cast(pl.Utf8).str.strip_chars().str.replace_all(':', '')
    time_digits = time_text.str.extract(r'(\d{3,6})$').fill_null('145000')
    hhmmss_expr = (
        pl.when(time_digits.str.len_chars() <= 4)
        .then(time_digits.cast(pl.Int64, strict=False) * 100)
        .otherwise(time_digits.cast(pl.Int64, strict=False))
        .fill_null(145000)
        .alias('hhmmss')
    )

    flow_lazy = (
        lf.select([
            pl.col('ts_code').cast(pl.Utf8).alias('ts_code'),
            pl.col('trade_date').cast(pl.Utf8).str.replace_all('-', '').str.slice(0, 8).alias('trade_date'),
            time_expr.alias('_trade_time'),
            open_expr.cast(pl.Float64, strict=False).alias('open'),
            pl.col('close').cast(pl.Float64, strict=False).alias('close'),
            amount_expr.cast(pl.Float64, strict=False).alias('amount'),
        ])
        .with_columns([hhmmss_expr])
        .filter(
            (pl.col('hhmmss') <= 145000)
            & pl.col('ts_code').is_not_null()
            & pl.col('trade_date').is_not_null()
            & pl.col('open').is_not_null()
            & pl.col('close').is_not_null()
            & pl.col('amount').is_not_null()
            & (pl.col('open') > 0)
            & (pl.col('amount').abs() > 0)
        )
        .with_columns([
            (pl.col('close') / pl.col('open') - 1.0).alias('bar_ret'),
            pl.col('amount').abs().alias('amt_abs'),
        ])
        .with_columns([
            (pl.col('bar_ret').sign() * pl.col('amt_abs')).alias('signed_amt'),
            (pl.col('amt_abs') * pl.col('amt_abs')).alias('amt_sq'),
            pl.col('bar_ret').abs().alias('abs_bar_ret'),
        ])
        .group_by(['ts_code', 'trade_date'])
        .agg([
            pl.col('signed_amt').sum().alias('signed_amt_sum'),
            pl.col('amt_abs').sum().alias('gross_amt'),
            pl.col('amt_sq').sum().alias('amt_sq_sum'),
            pl.col('abs_bar_ret').sum().alias('abs_ret_sum'),
            pl.col('bar_ret').std().alias('ret_std'),
            pl.col('bar_ret').count().alias('minute_count'),
        ])
    )
    flow_pl = _collect_polars_lazy(flow_lazy)
    flow_pd = flow_pl.to_pandas()
    return flow_pd, {
        **(meta or {}),
        'source': 'polars_local_minute_partition_daily_flow_preaggregation',
        'engine': 'polars',
        'polars_version': getattr(pl, '__version__', None),
        'row_count': int(len(flow_pd)),
        'seconds': time.perf_counter() - started,
    }


def _intraday_flow_daily_cache_path(dates: list[str], minute_query: dict[str, Any]) -> Path | None:
    if os.environ.get('FACTORFORGE_STEP4_FLOW_DAILY_CACHE_DISABLE') == '1':
        return None
    cache_root_text = os.environ.get('FACTORFORGE_STEP4_FLOW_DAILY_CACHE')
    if cache_root_text:
        cache_root = Path(cache_root_text)
    elif os.environ.get('FACTORFORGE_DATA_CACHE'):
        cache_root = Path(os.environ['FACTORFORGE_DATA_CACHE']) / 'derived_features' / 'intraday_flow_daily_sp3'
    else:
        return None
    key_payload = {
        'version': 'intraday_flow_daily_sp3_v2',
        'date_start': dates[0] if dates else None,
        'date_end': dates[-1] if dates else None,
        'date_count': len(dates),
        'fields': sorted(str(field) for field in (minute_query.get('fields') or [])),
    }
    cache_key = hashlib.sha256(json.dumps(key_payload, sort_keys=True).encode('utf-8')).hexdigest()[:16]
    return cache_root / f"intraday_flow_daily_sp3__{dates[0]}__{dates[-1]}__{len(dates)}d__{cache_key}.parquet"


def _compute_sp3_from_intraday_flow_daily(daily_df: pd.DataFrame, flow_daily: pd.DataFrame) -> pd.DataFrame:
    daily = daily_df.copy()
    daily['trade_date'] = _normal_date_text(daily['trade_date'])
    agg = flow_daily.copy()
    agg['trade_date'] = _normal_date_text(agg['trade_date'])
    agg = agg[agg['gross_amt'] > 0].copy()
    agg['net_flow_ratio'] = agg['signed_amt_sum'] / agg['gross_amt']
    agg['flow_hhi'] = agg['amt_sq_sum'] / (agg['gross_amt'] * agg['gross_amt'])
    agg['impact_efficiency'] = agg['abs_ret_sum'] / (agg['net_flow_ratio'].abs() + 1e-6)
    agg['hhi_impact'] = agg['flow_hhi'] * agg['impact_efficiency']
    agg['h1_raw'] = _z_by_trade_date(agg, 'net_flow_ratio') + _z_by_trade_date(agg, 'hhi_impact')
    agg['h1'] = _z_by_trade_date(agg, 'h1_raw')

    control_cols = ['total_mv', 'turnover_rate', 'turnover_rate_f', 'volume_ratio']
    keep = ['ts_code', 'trade_date'] + [col for col in control_cols if col in daily.columns]
    controls = daily[keep].copy().sort_values(['ts_code', 'trade_date'])
    for col in control_cols:
        if col not in controls.columns:
            controls[col] = np.nan
        controls[col] = pd.to_numeric(controls[col], errors='coerce')
        controls[col + '_lag1'] = controls.groupby('ts_code', sort=False)[col].shift(1)
    controls = controls[['ts_code', 'trade_date'] + [col + '_lag1' for col in control_cols]]
    out = agg.merge(controls, on=['ts_code', 'trade_date'], how='left')
    out['ln_total_mv'] = np.log(out['total_mv_lag1'].where(out['total_mv_lag1'] > 0))
    z_inputs = {
        'ln_total_mv_z': 'ln_total_mv',
        'turnover_z': 'turnover_rate_lag1',
        'turnover_f_z': 'turnover_rate_f_lag1',
        'volume_ratio_z': 'volume_ratio_lag1',
    }
    for z_col, raw_col in z_inputs.items():
        out[z_col] = _z_by_trade_date(out, raw_col)
    size_strip = 0.10 * out['ln_total_mv_z'].fillna(0.0)
    float_turnover_strip = 0.05 * out['turnover_f_z'].fillna(0.0)
    crowding_penalty = 0.25 * out['volume_ratio_z'].abs().fillna(0.0) + 0.15 * out['turnover_z'].abs().fillna(0.0)
    out['factor_value'] = out['h1'].fillna(0.0) - size_strip - float_turnover_strip - crowding_penalty
    out = out.replace([np.inf, -np.inf], np.nan).dropna(subset=['factor_value'])
    return out[['ts_code', 'trade_date', 'factor_value']].sort_values(['ts_code', 'trade_date']).reset_index(drop=True)


def _supports_sp3_intraday_flow_fast_path(module: Any) -> bool:
    try:
        fn = getattr(module, '_factorforge_user_compute_factor', getattr(module, 'compute_factor'))
        source = inspect.getsource(fn)
    except (OSError, TypeError):
        return False
    required_tokens = [
        'net_flow_ratio',
        'flow_hhi',
        'hhi_impact',
        'volume_ratio_lag1',
        'turnover_rate_f_lag1',
        'crowding_penalty',
    ]
    return all(token in source for token in required_tokens)


def compute_factor_intraday_flow_daily_preagg_contract(
    *,
    daily_df: pd.DataFrame,
    minute_query: dict[str, Any],
    report_id: str,
    run_dir: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    started = time.perf_counter()
    daily = daily_df.copy()
    if 'trade_date' not in daily.columns:
        raise SystemExit('BLOCK_STEP4_FLOW_PREAGG_DAILY_DATE_MISSING: daily_df missing trade_date')
    daily['trade_date'] = _normal_date_text(daily['trade_date'])
    all_dates = sorted(str(x) for x in daily['trade_date'].dropna().unique())
    query_start = str(minute_query.get('start_date') or all_dates[0])
    query_end = str(minute_query.get('end_date') or all_dates[-1])
    dates = [date for date in all_dates if query_start <= date <= query_end]
    if not dates:
        raise SystemExit('BLOCK_STEP4_FLOW_PREAGG_WINDOW_EMPTY: no daily dates overlap minute query')
    batch_size = max(1, int(os.environ.get('FACTORFORGE_STEP4_MINUTE_STREAM_BATCH_DAYS', '5') or '5'))
    batches = _batched(dates, batch_size)

    cache_path = _intraday_flow_daily_cache_path(dates, minute_query)
    cache_hit = False
    if cache_path and cache_path.exists():
        flow_daily = pd.read_parquet(cache_path)
        cache_hit = True
        batch_profiles = [{
            'status': 'cache_hit',
            'cache_path': str(cache_path),
            'flow_rows': int(len(flow_daily)),
        }]
    else:
        flow_daily = None
        batch_profiles = []

    flow_chunks: list[pd.DataFrame] = []
    if flow_daily is None:
        for batch_index, batch_dates in enumerate(batches):
            fetch_started = time.perf_counter()
            flow_chunk, polars_meta = _aggregate_intraday_flow_daily_polars_for_dates(batch_dates)
            if flow_chunk is not None:
                fetch_seconds = 0.0
                agg_seconds = float((polars_meta or {}).get('seconds') or (time.perf_counter() - fetch_started))
                minute_rows = None
                minute_meta = polars_meta or {}
            else:
                minute_df, minute_meta = _fetch_minute_frame_for_dates(minute_query, batch_dates)
                fetch_seconds = time.perf_counter() - fetch_started
                agg_started = time.perf_counter()
                flow_chunk = _aggregate_intraday_flow_daily(minute_df)
                agg_seconds = time.perf_counter() - agg_started
                minute_rows = int(len(minute_df))
                del minute_df
            if len(flow_chunk):
                flow_chunks.append(flow_chunk)
            batch_profiles.append({
                'batch_index': batch_index,
                'date_start': batch_dates[0],
                'date_end': batch_dates[-1],
                'date_count': len(batch_dates),
                'minute_rows': minute_rows,
                'flow_rows': int(len(flow_chunk)),
                'fetch_seconds': fetch_seconds,
                'aggregate_seconds': agg_seconds,
                'status': 'ready',
                'metadata': minute_meta,
            })
            del flow_chunk
            gc.collect()

        if flow_chunks:
            flow_daily = pd.concat(flow_chunks, ignore_index=True)
        else:
            flow_daily = pd.DataFrame(columns=[
                'ts_code', 'trade_date', 'signed_amt_sum', 'gross_amt', 'amt_sq_sum',
                'abs_ret_sum', 'ret_std', 'minute_count',
            ])
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            flow_daily.to_parquet(cache_path, index=False)
    flow_path = run_dir / 'step4_data_inputs' / f'intraday_flow_daily__{report_id}.parquet'
    flow_path.parent.mkdir(parents=True, exist_ok=True)
    flow_daily.to_parquet(flow_path, index=False)

    compute_started = time.perf_counter()
    result = _compute_sp3_from_intraday_flow_daily(daily, flow_daily)
    compute_seconds = time.perf_counter() - compute_started
    profile = {
        'version': 'factorforge_step4_intraday_flow_daily_preagg_profile_v1',
        'source': 'local_minute_partitions_to_daily_flow_preaggregation',
        'partition_key': 'trade_date',
        'date_count': len(dates),
        'date_start': dates[0],
        'date_end': dates[-1],
        'batch_size_days': batch_size,
        'batch_count': len(batches),
        'flow_daily_path': str(flow_path),
        'persistent_cache_path': str(cache_path) if cache_path else None,
        'persistent_cache_hit': cache_hit,
        'total_minute_rows': int(sum(item.get('minute_rows') or 0 for item in batch_profiles)),
        'total_flow_rows': int(len(flow_daily)),
        'total_factor_rows': int(len(result)),
        'total_fetch_seconds': float(sum(item.get('fetch_seconds') or 0.0 for item in batch_profiles)),
        'total_aggregate_seconds': float(sum(item.get('aggregate_seconds') or 0.0 for item in batch_profiles)),
        'final_factor_compute_seconds': compute_seconds,
        'total_seconds': time.perf_counter() - started,
        'batch_profiles_head': batch_profiles[:5],
        'batch_profiles_tail': batch_profiles[-5:],
    }
    return result, profile


def compute_factor_streaming_minute_contract(
    module: Any,
    *,
    daily_df: pd.DataFrame,
    minute_query: dict[str, Any],
    report_id: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    started = time.perf_counter()
    daily = daily_df.copy()
    if 'trade_date' not in daily.columns:
        raise SystemExit('BLOCK_STEP4_STREAMING_DAILY_DATE_MISSING: daily_df missing trade_date')
    daily['trade_date'] = _normal_date_text(daily['trade_date'])
    all_dates = sorted(str(x) for x in daily['trade_date'].dropna().unique())
    query_start = str(minute_query.get('start_date') or all_dates[0])
    query_end = str(minute_query.get('end_date') or all_dates[-1])
    dates = [date for date in all_dates if query_start <= date <= query_end]
    if not dates:
        raise SystemExit('BLOCK_STEP4_STREAMING_WINDOW_EMPTY: no daily dates overlap minute query')
    batch_size = max(1, int(os.environ.get('FACTORFORGE_STEP4_MINUTE_STREAM_BATCH_DAYS', '5') or '5'))
    batches = _batched(dates, batch_size)
    previous_by_date = {date: (all_dates[idx - 1] if idx > 0 else None) for idx, date in enumerate(all_dates)}

    chunks: list[pd.DataFrame] = []
    batch_profiles: list[dict[str, Any]] = []
    for batch_index, batch_dates in enumerate(batches):
        batch_start, batch_end = batch_dates[0], batch_dates[-1]
        fetch_started = time.perf_counter()
        minute_df, minute_meta = _fetch_minute_frame_for_dates(minute_query, batch_dates)
        fetch_seconds = time.perf_counter() - fetch_started
        if minute_df is None or len(minute_df) == 0:
            batch_profiles.append({
                'batch_index': batch_index,
                'date_start': batch_start,
                'date_end': batch_end,
                'date_count': len(batch_dates),
                'minute_rows': 0,
                'factor_rows': 0,
                'fetch_seconds': fetch_seconds,
                'compute_seconds': 0.0,
                'status': 'empty_minute_partition',
                'metadata': minute_meta,
            })
            continue
        if 'trade_date' in minute_df.columns:
            minute_df = minute_df.copy()
            minute_df['trade_date'] = _normal_date_text(minute_df['trade_date'])
        previous_date = previous_by_date.get(batch_start)
        daily_dates = ([previous_date] if previous_date else []) + batch_dates
        daily_slice = daily[daily['trade_date'].isin(daily_dates)].copy()
        compute_started = time.perf_counter()
        chunk = compute_factor_with_contract(module, daily_slice, minute_df)
        compute_seconds = time.perf_counter() - compute_started
        if isinstance(chunk, pd.DataFrame) and len(chunk):
            if 'trade_date' in chunk.columns:
                chunk = chunk.copy()
                chunk['trade_date'] = _normal_date_text(chunk['trade_date'])
                chunk = chunk[chunk['trade_date'].isin(batch_dates)].copy()
            if len(chunk):
                chunks.append(chunk)
        batch_profiles.append({
            'batch_index': batch_index,
            'date_start': batch_start,
            'date_end': batch_end,
            'date_count': len(batch_dates),
            'minute_rows': int(len(minute_df)),
            'factor_rows': int(len(chunk)) if isinstance(chunk, pd.DataFrame) else 0,
            'fetch_seconds': fetch_seconds,
            'compute_seconds': compute_seconds,
            'status': 'ready',
            'metadata': minute_meta,
        })

    if chunks:
        result = pd.concat(chunks, ignore_index=True)
    else:
        result = pd.DataFrame(columns=['ts_code', 'trade_date', 'factor_value'])
    profile = {
        'version': 'factorforge_step4_minute_streaming_profile_v1',
        'source': 'factorforge_data_api_partition_streaming',
        'partition_key': 'trade_date',
        'date_count': len(dates),
        'date_start': dates[0],
        'date_end': dates[-1],
        'batch_size_days': batch_size,
        'batch_count': len(batches),
        'total_minute_rows': int(sum(item.get('minute_rows') or 0 for item in batch_profiles)),
        'total_factor_rows': int(len(result)),
        'total_fetch_seconds': float(sum(item.get('fetch_seconds') or 0.0 for item in batch_profiles)),
        'total_compute_seconds': float(sum(item.get('compute_seconds') or 0.0 for item in batch_profiles)),
        'total_seconds': time.perf_counter() - started,
        'batch_profiles_head': batch_profiles[:5],
        'batch_profiles_tail': batch_profiles[-5:],
    }
    return result, profile


def _step4_data_contract(dpm: dict[str, Any], handoff: dict[str, Any]) -> dict[str, Any]:
    local_inputs = dpm.get('local_input_paths') if isinstance(dpm.get('local_input_paths'), dict) else {}
    for candidate in (
        handoff.get('step4_data_contract'),
        dpm.get('step4_data_contract'),
        local_inputs.get('step4_data_contract'),
    ):
        if isinstance(candidate, dict) and candidate:
            return candidate
    return {}


def _contract_query(contract: dict[str, Any], query_set: str, dataset_id: str) -> dict[str, Any] | None:
    queries = contract.get(query_set) if isinstance(contract, dict) else None
    if not isinstance(queries, dict):
        return None
    query = queries.get(dataset_id)
    if not isinstance(query, dict):
        return None
    if contract.get('catalog_path') and not query.get('catalog_path'):
        return {**query, 'catalog_path': contract.get('catalog_path')}
    return query


def _minute_derived_state_requirements(contract: dict[str, Any], dpm: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    for source in (contract, dpm or {}):
        raw = source.get('minute_derived_state_requirements') if isinstance(source, dict) else None
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
    return []


def _minute_flow_state_requirement(contract: dict[str, Any], dpm: dict[str, Any] | None = None) -> dict[str, Any] | None:
    for requirement in _minute_derived_state_requirements(contract, dpm):
        dataset_id = str(requirement.get('dataset_id') or '').strip()
        if dataset_id:
            return requirement
    return None


def _research_window_contract(contract: dict[str, Any], dpm: dict[str, Any]) -> dict[str, Any]:
    candidate = contract.get('research_window_contract') if isinstance(contract, dict) else None
    if isinstance(candidate, dict) and candidate:
        return candidate
    candidate = dpm.get('research_window_contract') if isinstance(dpm, dict) else None
    if isinstance(candidate, dict) and candidate:
        return candidate
    return default_research_window_contract(dpm.get('sample_window') if isinstance(dpm, dict) else {})


def _daily_trade_dates_for_minute_query(daily_df: pd.DataFrame, minute_query: dict[str, Any]) -> list[str]:
    if 'trade_date' not in daily_df.columns:
        raise SystemExit('BLOCK_STEP4_STREAMING_DAILY_DATE_MISSING: daily_df missing trade_date')
    dates = sorted(str(x) for x in _normal_date_text(daily_df['trade_date']).dropna().unique())
    if not dates:
        return []
    query_start = normalize_trade_date(minute_query.get('start_date') or dates[0])
    query_end = normalize_trade_date(minute_query.get('end_date') or dates[-1])
    return [date for date in dates if query_start <= date <= query_end]


def _generic_minute_full_window_forbidden(dates: list[str]) -> bool:
    if os.getenv('FACTORFORGE_ALLOW_GENERIC_MINUTE_FULL_WINDOW') == '1':
        return False
    max_days = int(os.getenv('FACTORFORGE_STEP4_GENERIC_MINUTE_MAX_DAYS', '120') or '120')
    return len(dates) > max_days


def _catalog_dataset_columns(dataset_id: str, catalog_path: str | Path | None) -> set[str] | None:
    if not catalog_path:
        return None
    path = Path(catalog_path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None
    datasets = payload.get('datasets') if isinstance(payload, dict) else None
    entry = datasets.get(dataset_id) if isinstance(datasets, dict) else None
    if not isinstance(entry, dict):
        entry = payload.get(dataset_id) if isinstance(payload, dict) else None
    if not isinstance(entry, dict):
        return None
    columns = entry.get('columns')
    if columns is None and isinstance(entry.get('schema'), dict):
        columns = entry['schema'].get('columns')
    if isinstance(columns, dict):
        columns = list(columns)
    if not isinstance(columns, list):
        return None
    return {str(column) for column in columns}


def _load_required_minute_flow_state(
    *,
    requirement: dict[str, Any],
    daily_df: pd.DataFrame,
    minute_query: dict[str, Any],
    required_dates: list[str] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    dates = required_dates or _daily_trade_dates_for_minute_query(daily_df, minute_query)
    if not dates:
        raise SystemExit('BLOCK_STEP4_FLOW_PREAGG_WINDOW_EMPTY: no daily dates overlap minute query')
    dataset_id = str(requirement.get('dataset_id') or MINUTE_DERIVED_FLOW_STATE_V1).strip()
    root = requirement.get('local_warm_cache_root') or requirement.get('root')
    cutoff_time = requirement.get('cutoff_time') or DEFAULT_MINUTE_CUTOFF_TIME
    source_data_version = requirement.get('source_data_version')
    fields = requirement.get('required_fields') or FLOW_STATE_REQUIRED_COLUMNS
    if dataset_id != MINUTE_DERIVED_FLOW_STATE_V1:
        catalog_path = requirement.get('catalog_path') or minute_query.get('catalog_path')
        catalog_columns = _catalog_dataset_columns(dataset_id, catalog_path)
        include_cutoff_field = 'cutoff_time' in fields
        if catalog_columns is not None:
            include_cutoff_field = include_cutoff_field or 'cutoff_time' in catalog_columns
        else:
            include_cutoff_field = bool(requirement.get('requires_cutoff_time_column'))
        required_fields = list(dict.fromkeys([
            *fields,
            'ts_code',
            'trade_date',
            *(['cutoff_time'] if include_cutoff_field else []),
        ]))
        started = time.perf_counter()
        if dataset_id in TRADE_DATE_FETCH_STATE_DATASETS:
            frames: list[pd.DataFrame] = []
            date_profiles: list[dict[str, Any]] = []
            for date in dates:
                date_result = fetch_data_api_dataset(
                    dataset_id,
                    start=date,
                    end=date,
                    fields=required_fields,
                    universe=minute_query.get('universe') or 'a_share_all',
                    frequency=requirement.get('frequency') or 'daily',
                    catalog_path=catalog_path,
                )
                if date_result.status not in {'ready', 'proxy_ready'}:
                    raise SystemExit(
                        f"BLOCK_STEP4_MINUTE_DERIVED_STATE_FETCH_FAILED: {dataset_id} "
                        f"date={date} status={date_result.status} reason={date_result.blocked_reason}"
                    )
                if not date_result.frame.empty:
                    frames.append(date_result.frame.copy())
                date_profiles.append({
                    'trade_date': date,
                    'status': date_result.status,
                    'row_count': int(len(date_result.frame)),
                    'blocked_reason': date_result.blocked_reason,
                })
            frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=required_fields)
            result_metadata = {
                'date_fetch_count': len(date_profiles),
                'date_fetch_empty_count': sum(1 for item in date_profiles if int(item.get('row_count') or 0) == 0),
                'date_fetch_rows': sum(int(item.get('row_count') or 0) for item in date_profiles),
                'date_fetch_profile_sample': date_profiles[:3] + date_profiles[-3:] if len(date_profiles) > 6 else date_profiles,
            }
        else:
            result = fetch_data_api_dataset(
                dataset_id,
                start=dates[0],
                end=dates[-1],
                fields=required_fields,
                universe=minute_query.get('universe') or 'a_share_all',
                frequency=requirement.get('frequency') or 'daily',
                catalog_path=catalog_path,
            )
            if result.status not in {'ready', 'proxy_ready'}:
                raise SystemExit(
                    f"BLOCK_STEP4_MINUTE_DERIVED_STATE_FETCH_FAILED: {dataset_id} "
                    f"status={result.status} reason={result.blocked_reason}"
                )
            frame = result.frame.copy()
            result_metadata = result.to_metadata()
        rows_before_cutoff = int(len(frame))
        if 'cutoff_time' in frame.columns:
            normalized_cutoff = normalize_cutoff_time(cutoff_time)
            cutoff_series = frame['cutoff_time'].map(
                lambda value: normalize_cutoff_time(value) if pd.notna(value) else ''
            )
            frame = frame.loc[cutoff_series == normalized_cutoff].copy()
        if 'trade_date' in frame.columns:
            expected_dates = set(dates)
            frame['_factorforge_trade_date_norm'] = _normal_date_text(frame['trade_date'])
            frame = frame.loc[frame['_factorforge_trade_date_norm'].isin(expected_dates)].drop(columns=['_factorforge_trade_date_norm']).copy()
        if frame.empty:
            raise SystemExit(
                f"BLOCK_STEP4_MINUTE_DERIVED_STATE_EMPTY: {dataset_id} cutoff_time={cutoff_time} "
                f"date_window={dates[0]}..{dates[-1]}"
            )
        profile = dict(result_metadata)
        profile.update({
            'dataset_id': dataset_id,
            'cutoff_time': normalize_cutoff_time(cutoff_time),
            'rows_before_cutoff_filter': rows_before_cutoff,
            'rows_after_cutoff_filter': int(len(frame)),
            'date_count_after_filter': int(frame['trade_date'].nunique()) if 'trade_date' in frame.columns else None,
            'ticker_count_after_filter': int(frame['ts_code'].nunique()) if 'ts_code' in frame.columns else None,
            'load_seconds': time.perf_counter() - started,
            'load_mode': 'data_api_minute_derived_state_by_trade_date'
            if dataset_id in TRADE_DATE_FETCH_STATE_DATASETS
            else 'data_api_minute_derived_state',
        })
        return frame, profile

    loaded = load_flow_state_partitions(
        start_date=dates[0],
        end_date=dates[-1],
        required_dates=dates,
        root=root,
        cutoff_time=cutoff_time,
        source_data_version=source_data_version,
        required_fields=fields,
    )
    if loaded.status == 'ready':
        return loaded.frame, loaded.profile
    blocker = loaded.profile.get('blocker') or 'BLOCK_MINUTE_DERIVED_STATE_COVERAGE_INCOMPLETE'
    raise SystemExit(f"{blocker}: {json.dumps(loaded.profile, ensure_ascii=False, sort_keys=True, default=str)}")


def compute_factor_from_data_api_minute_derived_state_batches(
    module: Any,
    *,
    daily_df: pd.DataFrame,
    requirement: dict[str, Any],
    minute_query: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    dates = _daily_trade_dates_for_minute_query(daily_df, minute_query)
    if not dates:
        raise SystemExit('BLOCK_STEP4_FLOW_PREAGG_WINDOW_EMPTY: no daily dates overlap minute query')
    batch_size = int(os.getenv('FACTORFORGE_STEP4_DERIVED_STATE_BATCH_DAYS', '20') or '20')
    batch_size = max(1, batch_size)
    daily_work = daily_df.copy()
    daily_work['_factorforge_trade_date_norm'] = _normal_date_text(daily_work['trade_date'])
    results: list[pd.DataFrame] = []
    batch_profiles: list[dict[str, Any]] = []
    total_loaded_rows = 0
    total_factor_rows = 0
    total_load_seconds = 0.0
    total_compute_seconds = 0.0
    for start_idx in range(0, len(dates), batch_size):
        batch_dates = dates[start_idx:start_idx + batch_size]
        daily_dates = set(batch_dates)
        if start_idx > 0:
            daily_dates.add(dates[start_idx - 1])
        daily_slice = daily_work.loc[daily_work['_factorforge_trade_date_norm'].isin(daily_dates)].drop(columns=['_factorforge_trade_date_norm']).copy()
        flow_state_df, load_profile = _load_required_minute_flow_state(
            requirement=requirement,
            daily_df=daily_slice,
            minute_query=minute_query,
            required_dates=batch_dates,
        )
        batch_result, compute_profile = compute_factor_from_minute_derived_state(
            module,
            daily_df=daily_slice,
            flow_state_df=flow_state_df,
            dataset_id=str(requirement.get('dataset_id') or MINUTE_DERIVED_FLOW_STATE_V1),
        )
        if not batch_result.empty and 'trade_date' in batch_result.columns:
            normalized_result_dates = _normal_date_text(batch_result['trade_date'])
            batch_result = batch_result.loc[normalized_result_dates.isin(set(batch_dates))].copy()
        results.append(batch_result)
        total_loaded_rows += int(len(flow_state_df))
        total_factor_rows += int(len(batch_result))
        total_load_seconds += float(load_profile.get('load_seconds') or 0.0)
        total_compute_seconds += float(compute_profile.get('factor_compute_seconds') or 0.0)
        batch_profiles.append({
            'batch_index': len(batch_profiles),
            'start_date': batch_dates[0],
            'end_date': batch_dates[-1],
            'date_count': len(batch_dates),
            'derived_state_rows': int(len(flow_state_df)),
            'factor_rows': int(len(batch_result)),
            'load_seconds': float(load_profile.get('load_seconds') or 0.0),
            'factor_compute_seconds': float(compute_profile.get('factor_compute_seconds') or 0.0),
        })
        del flow_state_df, batch_result, daily_slice
        gc.collect()
    result_df = pd.concat(results, ignore_index=True) if results else pd.DataFrame(columns=['ts_code', 'trade_date', 'factor_value'])
    state_profile = {
        'status': 'ready',
        'dataset_id': str(requirement.get('dataset_id') or MINUTE_DERIVED_FLOW_STATE_V1),
        'load_mode': 'data_api_minute_derived_state_batched',
        'batch_size_days': int(batch_size),
        'batch_count': len(batch_profiles),
        'date_count': len(dates),
        'start_date': dates[0],
        'end_date': dates[-1],
        'derived_state_rows': int(total_loaded_rows),
        'factor_rows': int(total_factor_rows),
        'load_seconds': float(total_load_seconds),
        'total_seconds': float(time.perf_counter() - started),
        'batch_profiles_head': batch_profiles[:5],
        'batch_profiles_tail': batch_profiles[-5:],
    }
    factor_profile = {
        'source': 'step4_minute_derived_flow_state',
        'dataset_id': str(requirement.get('dataset_id') or MINUTE_DERIVED_FLOW_STATE_V1),
        'compute_mode': 'batched_module_compute_factor_from_derived_state',
        'batch_count': len(batch_profiles),
        'factor_compute_seconds': float(total_compute_seconds),
        'derived_state_rows': int(total_loaded_rows),
        'factor_rows': int(total_factor_rows),
    }
    return result_df, state_profile, factor_profile


def compute_factor_from_minute_derived_state(
    module: Any,
    *,
    daily_df: pd.DataFrame,
    flow_state_df: pd.DataFrame,
    dataset_id: str = MINUTE_DERIVED_FLOW_STATE_V1,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    compute_started = time.perf_counter()
    if hasattr(module, 'compute_factor_from_derived_state'):
        result = normalize_direct_code_result(module.compute_factor_from_derived_state(daily_df=daily_df, derived_state_df=flow_state_df))
        mode = 'module_compute_factor_from_derived_state'
    elif _supports_sp3_intraday_flow_fast_path(module):
        result = _compute_sp3_from_intraday_flow_daily(daily_df, flow_state_df)
        mode = 'step4_builtin_sp3_from_minute_derived_flow_state'
    else:
        try:
            result = compute_factor_with_contract(module, daily_df, flow_state_df)
            mode = 'module_compute_factor_with_derived_state_as_minute_df'
        except Exception as exc:
            raise SystemExit(
                'BLOCK_STEP4_MINUTE_DERIVED_STATE_REQUIRED: '
                'minute factor has derived-state requirement, but implementation cannot consume '
                f'{dataset_id}; add compute_factor_from_derived_state or regenerate direct_code. '
                f'error={type(exc).__name__}:{exc}'
            ) from exc
    if not isinstance(result, pd.DataFrame):
        raise SystemExit('BLOCK_STEP4_MINUTE_DERIVED_STATE_REQUIRED: derived-state compute did not return DataFrame')
    return result, {
        'source': 'step4_minute_derived_flow_state',
        'dataset_id': dataset_id,
        'compute_mode': mode,
        'factor_compute_seconds': time.perf_counter() - compute_started,
        'derived_state_rows': int(len(flow_state_df)),
        'factor_rows': int(len(result)),
    }


def _fetch_contract_frame(query: dict[str, Any]):
    result = fetch_data_api_dataset(
        str(query.get('dataset')),
        start=str(query.get('start_date')),
        end=str(query.get('end_date')),
        fields=list(query.get('fields') or []),
        universe=query.get('universe') or 'a_share_all',
        frequency=query.get('frequency'),
        catalog_path=query.get('catalog_path'),
    )
    if result.status not in {'ready', 'proxy_ready'}:
        raise SystemExit(
            f"BLOCK_STEP4_DATA_API_FETCH_FAILED: {query.get('dataset')} "
            f"status={result.status} reason={result.blocked_reason}"
        )
    return result.frame, result.to_metadata()


def _stable_json_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode('utf-8')).hexdigest()


def _backtest_base_cache_root() -> Path:
    explicit = os.getenv('FACTORFORGE_BACKTEST_BASE_CACHE_ROOT')
    if explicit:
        return Path(explicit).expanduser()
    cache_root = os.getenv('FACTORFORGE_DATA_CACHE')
    if cache_root:
        return Path(cache_root).expanduser() / 'backtest_base_daily_controls_v1'
    worker_cache = Path('/home/ubuntu/factorforge_data_api_cache/backtest_base_daily_controls_v1')
    if worker_cache.exists() or worker_cache.parent.exists():
        return worker_cache
    return Path.home() / '.cache' / 'factorforge_data_api' / 'backtest_base_daily_controls_v1'


def _backtest_base_identity(contract: dict[str, Any]) -> dict[str, Any]:
    full_queries = contract.get('full_queries') if isinstance(contract.get('full_queries'), dict) else {}
    relevant_queries = {
        key: full_queries.get(key)
        for key in ['clean_daily_bar', 'daily_basic']
        if full_queries.get(key)
    }
    return {
        'version': 'backtest_base_daily_controls_v1',
        'contract_version': contract.get('version'),
        'data_api_package': contract.get('data_api_package'),
        'catalog_path': contract.get('catalog_path'),
        'queries': relevant_queries,
    }


def _contract_flag(contract: dict[str, Any], key: str) -> bool:
    value = contract.get(key)
    if value is None and isinstance(contract.get('performance_contract'), dict):
        value = contract['performance_contract'].get(key)
    if value is None and isinstance(contract.get('reuse_contract'), dict):
        value = contract['reuse_contract'].get(key)
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on', 'required'}
    return bool(value)


def _backtest_base_min_control_tickers() -> int:
    raw = os.getenv('FACTORFORGE_BACKTEST_BASE_MIN_CONTROL_TICKERS', '100')
    try:
        return max(int(raw), 0)
    except ValueError:
        return 100


def _backtest_base_min_control_date_ratio() -> float:
    raw = os.getenv('FACTORFORGE_BACKTEST_BASE_MIN_CONTROL_DATE_RATIO', '0.95')
    try:
        return min(max(float(raw), 0.0), 1.0)
    except ValueError:
        return 0.95


def _daily_basic_control_columns_from_contract(contract: dict[str, Any]) -> list[str]:
    daily_basic_query = _contract_query(contract, 'full_queries', 'daily_basic')
    if not daily_basic_query:
        return []
    fields = daily_basic_query.get('fields')
    candidates: list[str] = []
    if isinstance(fields, list):
        candidates.extend(str(field) for field in fields)
    candidates.extend(['total_mv', 'turnover_rate', 'turnover_rate_f', 'volume_ratio'])
    alias_map = {
        'turnover': 'turnover_rate',
        'market_cap': 'total_mv',
        'circ_market_cap': 'circ_mv',
    }
    normalized: list[str] = []
    for column in candidates:
        resolved = alias_map.get(column, column)
        if resolved not in {'ts_code', 'trade_date'} and resolved not in normalized:
            normalized.append(resolved)
    return normalized


def _backtest_base_control_coverage(frame: pd.DataFrame, control_columns: list[str]) -> dict[str, Any]:
    coverage: dict[str, Any] = {}
    for column in control_columns:
        if column not in frame.columns:
            coverage[column] = {
                'present': False,
                'non_null_rows': 0,
                'non_null_ticker_count': 0,
                'non_null_date_count': 0,
            }
            continue
        mask = frame[column].notna()
        coverage[column] = {
            'present': True,
            'non_null_rows': int(mask.sum()),
            'non_null_ticker_count': int(frame.loc[mask, 'ts_code'].nunique()) if 'ts_code' in frame.columns else 0,
            'non_null_date_count': int(frame.loc[mask, 'trade_date'].nunique()) if 'trade_date' in frame.columns else 0,
        }
    return coverage


def _backtest_base_cache_control_violation(
    data_path: Path,
    contract: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any] | None:
    control_columns = _daily_basic_control_columns_from_contract(contract)
    if not control_columns:
        return None
    min_tickers = _backtest_base_min_control_tickers()
    if min_tickers <= 0:
        return None
    available_columns = metadata.get('columns') if isinstance(metadata.get('columns'), list) else []
    present_controls = [column for column in control_columns if column in available_columns]
    if not present_controls:
        return {
            'reason': 'daily_basic_control_columns_missing_from_cache',
            'required_control_columns': control_columns,
            'min_ticker_count': min_tickers,
        }
    read_columns = list(dict.fromkeys(['ts_code', 'trade_date'] + present_controls))
    try:
        frame = pd.read_parquet(data_path, columns=read_columns)
    except Exception as exc:
        return {
            'reason': 'daily_basic_control_coverage_read_failed',
            'error': str(exc),
            'required_control_columns': control_columns,
            'min_ticker_count': min_tickers,
        }
    coverage = _backtest_base_control_coverage(frame, present_controls)
    total_dates = int(frame['trade_date'].nunique()) if 'trade_date' in frame.columns and len(frame) else 0
    min_date_count = int(total_dates * _backtest_base_min_control_date_ratio())
    for column, stats in coverage.items():
        if stats.get('non_null_ticker_count', 0) < min_tickers:
            return {
                'reason': 'daily_basic_control_ticker_coverage_below_minimum',
                'column': column,
                'coverage': coverage,
                'min_ticker_count': min_tickers,
            }
        if stats.get('non_null_date_count', 0) < min_date_count:
            return {
                'reason': 'daily_basic_control_date_coverage_below_minimum',
                'column': column,
                'coverage': coverage,
                'total_dates': total_dates,
                'min_date_count': min_date_count,
                'min_date_ratio': _backtest_base_min_control_date_ratio(),
            }
    return None


def _backtest_base_cache_paths(contract: dict[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    identity = _backtest_base_identity(contract)
    identity_hash = _stable_json_hash(identity)
    cache_dir = _backtest_base_cache_root() / f'identity={identity_hash[:16]}'
    return (
        cache_dir / f'backtest_base_daily_controls_v1__{identity_hash[:16]}.parquet',
        cache_dir / f'backtest_base_daily_controls_v1__{identity_hash[:16]}.metadata.json',
        {**identity, 'identity_hash': identity_hash},
    )


def _load_backtest_base_cache(contract: dict[str, Any]) -> tuple[Path | None, dict[str, Any] | None]:
    data_path, meta_path, identity = _backtest_base_cache_paths(contract)
    if not data_path.exists() or not meta_path.exists():
        return None, None
    try:
        metadata = load_json(meta_path)
    except Exception:
        return None, None
    if metadata.get('identity_hash') != identity.get('identity_hash'):
        return None, None
    control_violation = _backtest_base_cache_control_violation(data_path, contract, metadata)
    if control_violation:
        return None, None
    return data_path, {
        'version': 'factorforge_backtest_base_reuse_profile_v1',
        'dataset_id': 'backtest_base_daily_controls_v1',
        'backtest_base_reuse_hit': True,
        'backtest_base_cache_path': str(data_path),
        'backtest_base_metadata_path': str(meta_path),
        'identity_hash': identity.get('identity_hash'),
        'row_count': metadata.get('row_count'),
        'date_count': metadata.get('date_count'),
        'ticker_count': metadata.get('ticker_count'),
        'source': 'persistent_warm_cache',
    }


def _write_backtest_base_cache(
    daily_df: pd.DataFrame,
    contract: dict[str, Any],
    *,
    result_metadata: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    data_path, meta_path, identity = _backtest_base_cache_paths(contract)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    daily_df.to_parquet(data_path, index=False)
    metadata = {
        **identity,
        'dataset_id': 'backtest_base_daily_controls_v1',
        'path': str(data_path),
        'row_count': int(len(daily_df)),
        'date_count': int(daily_df['trade_date'].nunique()) if 'trade_date' in daily_df.columns and len(daily_df) else 0,
        'ticker_count': int(daily_df['ts_code'].nunique()) if 'ts_code' in daily_df.columns and len(daily_df) else 0,
        'columns': [str(col) for col in daily_df.columns],
        'artifact_hash': sha256_file(data_path),
        'result_metadata': result_metadata,
        'written_at_utc': utc_now(),
    }
    control_columns = _daily_basic_control_columns_from_contract(contract)
    if control_columns:
        metadata['daily_basic_control_coverage'] = _backtest_base_control_coverage(daily_df, control_columns)
    write_json(meta_path, metadata)
    return data_path, {
        'version': 'factorforge_backtest_base_reuse_profile_v1',
        'dataset_id': 'backtest_base_daily_controls_v1',
        'backtest_base_reuse_hit': False,
        'backtest_base_cache_path': str(data_path),
        'backtest_base_metadata_path': str(meta_path),
        'identity_hash': identity.get('identity_hash'),
        'row_count': metadata['row_count'],
        'date_count': metadata['date_count'],
        'ticker_count': metadata['ticker_count'],
        'source': 'rebuilt_and_cached',
    }


def materialize_step4_data_inputs_from_contract(
    report_id: str,
    contract: dict[str, Any],
    run_dir: Path,
) -> tuple[dict[str, str], dict[str, Any]]:
    if contract.get('version') != 'factorforge_step4_data_contract_v1':
        raise SystemExit('BLOCK_STEP4_DATA_CONTRACT_MISSING: Step4 requires factorforge_step4_data_contract_v1 when local inputs are absent')
    if contract.get('formal_factor_values_owner') != 'Step4':
        raise SystemExit('BLOCK_STEP4_DATA_CONTRACT_OWNER_INVALID: formal factor_values owner must be Step4')
    daily_query = _contract_query(contract, 'full_queries', 'clean_daily_bar')
    if not daily_query:
        raise SystemExit('BLOCK_STEP4_DATA_CONTRACT_MISSING: clean_daily_bar full query is required')

    data_dir = run_dir / 'step4_data_inputs'
    data_dir.mkdir(parents=True, exist_ok=True)

    cached_base_path, cached_base_profile = _load_backtest_base_cache(contract)
    if cached_base_path is not None and cached_base_profile is not None:
        local_inputs = {
            'input_mode': 'daily_only',
            'daily_df_parquet': str(cached_base_path),
            'data_source': 'factorforge_data_api_backtest_base_cache',
        }
        meta = {
            'backtest_base_daily_controls_v1': cached_base_profile,
            'cache_reuse': cached_base_profile,
        }
        moneyflow_query = _contract_query(contract, 'full_queries', 'moneyflow')
        if moneyflow_query:
            signal_df, signal_meta = _fetch_contract_frame(moneyflow_query)
            signal_path = data_dir / f'step4_signal_daily_input__{report_id}__moneyflow.parquet'
            signal_df.to_parquet(signal_path, index=False)
            local_inputs['input_mode'] = 'alternative_daily_plus_clean_daily'
            local_inputs['formula_input_dataset'] = 'moneyflow'
            local_inputs['signal_daily_df_parquet'] = str(signal_path)
            local_inputs['evaluation_daily_df_parquet'] = str(cached_base_path)
            meta['moneyflow'] = signal_meta
        minute_query = _contract_query(contract, 'full_queries', 'minute_bar')
        if minute_query:
            local_inputs['input_mode'] = 'price_volume_minute'
            local_inputs['minute_streaming_query'] = minute_query
            meta['minute_bar'] = {
                'dataset_id': minute_query.get('dataset'),
                'status': 'streaming_deferred',
                'request': minute_query,
                'streaming_policy': {
                    'version': 'factorforge_step4_minute_streaming_policy_v1',
                    'reason': 'avoid materializing full-window all-market minute data in memory',
                    'partition_key': 'trade_date',
                    'formal_factor_values_owner': 'Step4',
                },
            }
        return local_inputs, {
            'source': 'factorforge_data_api_full_query',
            'contract_version': contract.get('version'),
            'data_api_package': contract.get('data_api_package'),
            'catalog_path': contract.get('catalog_path'),
            'queries': contract.get('full_queries') or {},
            'result_metadata': meta,
            'backtest_base_reuse_profile': cached_base_profile,
        }
    if _contract_flag(contract, 'backtest_base_reuse_required'):
        raise SystemExit(
            'BLOCK_FACTORFORGE_BACKTEST_BASE_REUSE_REQUIRED: '
            'Step4 contract requires an existing reusable backtest_base_daily_controls_v1 artifact, '
            'but no matching persistent cache was found.'
        )

    daily_df, daily_meta = _fetch_contract_frame(daily_query)
    meta = {'clean_daily_bar': daily_meta}

    daily_basic_query = _contract_query(contract, 'full_queries', 'daily_basic')
    if daily_basic_query:
        daily_basic_df, daily_basic_meta = _fetch_contract_frame(daily_basic_query)
        daily_basic_perf = daily_basic_meta.get('performance_profile') if isinstance(daily_basic_meta, dict) else {}
        if _contract_flag(contract, 'daily_basic_parquet_required') and (
            not isinstance(daily_basic_perf, dict)
            or daily_basic_perf.get('daily_basic_selected_format') != 'parquet'
        ):
            raise SystemExit(
                'BLOCK_FACTORFORGE_DAILY_BASIC_PARQUET_REQUIRED: '
                'Step4 contract requires daily_basic parquet/warm-cache access, '
                f'but selected profile was {daily_basic_perf}'
            )
        overlap = [
            col for col in daily_basic_df.columns
            if col in daily_df.columns and col not in {'ts_code', 'trade_date'}
        ]
        if overlap:
            daily_basic_df = daily_basic_df.drop(columns=overlap)
        daily_df = daily_df.merge(daily_basic_df, on=['ts_code', 'trade_date'], how='left')
        meta['daily_basic'] = daily_basic_meta

    daily_path, backtest_base_profile = _write_backtest_base_cache(
        daily_df,
        contract,
        result_metadata=meta,
    )
    meta['backtest_base_daily_controls_v1'] = backtest_base_profile

    local_inputs = {
        'input_mode': 'daily_only',
        'daily_df_parquet': str(daily_path),
        'data_source': 'factorforge_data_api_full_query',
    }

    moneyflow_query = _contract_query(contract, 'full_queries', 'moneyflow')
    if moneyflow_query:
        signal_df, signal_meta = _fetch_contract_frame(moneyflow_query)
        signal_path = data_dir / f'step4_signal_daily_input__{report_id}__moneyflow.parquet'
        signal_df.to_parquet(signal_path, index=False)
        local_inputs['input_mode'] = 'alternative_daily_plus_clean_daily'
        local_inputs['formula_input_dataset'] = 'moneyflow'
        local_inputs['signal_daily_df_parquet'] = str(signal_path)
        local_inputs['evaluation_daily_df_parquet'] = str(daily_path)
        meta['moneyflow'] = signal_meta

    minute_query = _contract_query(contract, 'full_queries', 'minute_bar')
    if minute_query:
        local_inputs['input_mode'] = 'price_volume_minute'
        local_inputs['minute_streaming_query'] = minute_query
        meta['minute_bar'] = {
            'dataset_id': minute_query.get('dataset'),
            'status': 'streaming_deferred',
            'request': minute_query,
            'streaming_policy': {
                'version': 'factorforge_step4_minute_streaming_policy_v1',
                'reason': 'avoid materializing full-window all-market minute data in memory',
                'partition_key': 'trade_date',
                'formal_factor_values_owner': 'Step4',
            },
        }

    return local_inputs, {
        'source': 'factorforge_data_api_full_query',
        'contract_version': contract.get('version'),
        'data_api_package': contract.get('data_api_package'),
        'catalog_path': contract.get('catalog_path'),
        'queries': contract.get('full_queries') or {},
        'result_metadata': meta,
        'backtest_base_reuse_profile': backtest_base_profile,
    }


def build_failure_outputs(report_id: str, factor_id: str | None, implementation_path: str | None, sample_window: dict[str, Any], run_dir: Path, input_paths: dict[str, Path], issues: list[dict[str, Any]], warnings: list[str], failure_reason: str, failed_stage: str, start_utc: str, revision_of: str | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    run_master_path = OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json'
    diag_path = OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json'
    handoff_path = OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json'

    evaluation_plan = {
        'backends': [
            {'name': 'self_quant_analyzer', 'mode': 'quick'},
            {'name': 'qlib_backtest', 'mode': 'default'},
        ],
        'metric_policy': 'extensible',
    }
    backend_runs = build_backend_runs_stub(report_id, evaluation_plan, 'failed')

    run_master = {
        'report_id': report_id,
        'factor_id': factor_id,
        'run_status': 'failed',
        'implementation_path': implementation_path,
        'output_paths': [],
        'sample_window': sample_window or {},
        'runtime_notes': warnings + [f'failed_stage={failed_stage}'],
        'diagnostic_summary': {'row_count': 0, 'date_count': 0, 'ticker_count': 0},
        'evaluation_plan': evaluation_plan,
        'evaluation_results': {'backend_runs': backend_runs},
        'failure_reason': failure_reason,
        'started_at_utc': start_utc,
        'finished_at_utc': utc_now(),
        'input_paths': {k: str(v) for k, v in input_paths.items()},
        'validation_pointer': str(diag_path),
        'handoff_to_step5_path': str(handoff_path),
    }
    if revision_of:
        run_master['revision'] = {'revises': revision_of, 'reason': 'validator-directed explicit revision'}

    diagnostics = {
        'report_id': report_id,
        'factor_id': factor_id,
        'run_status': 'failed',
        'diagnostic_generated_at_utc': utc_now(),
        'evaluation_plan': evaluation_plan,
        'evaluation_results': {'backend_runs': backend_runs},
        'input_validation': {
            'exists_check': {k: v.exists() for k, v in input_paths.items()},
            'schema_check': {'frozen_schema_execution': True},
            'consistency_check': {},
            'placeholder_check': {}
        },
        'execution_trace': {
            'implementation_path': implementation_path,
            'commands': [],
            'runtime_seconds': None,
            'exception_type': None,
            'exception_message': failure_reason
        },
        'output_validation': {
            'output_exists': False,
            'output_paths': [],
            'file_sizes': {},
            'row_count': 0,
            'date_count': 0,
            'ticker_count': 0
        },
        'quality_checks': {
            'window_complete': False,
            'null_ratio': {},
            'duplicate_ratio': {},
            'key_uniqueness': {},
            'sort_order_ok': False
        },
        'issues': issues,
        'failure_context': {
            'failed_stage': failed_stage,
            'failure_reason': failure_reason,
            'retryable': True
        },
        'recommendation': {
            'can_handoff_to_step5': False,
            'recommended_status': 'failed',
            'next_action': 'Fix input/schema/implementation path and rerun Step 4.'
        }
    }

    handoff = {
        'report_id': report_id,
        'factor_id': factor_id,
        'run_status': 'failed',
        'factor_run_master_path': str(run_master_path),
        'diagnostics_path': str(diag_path),
        'output_paths': [],
        'sample_window_target': sample_window or {},
        'sample_window_actual': None,
        'coverage_ratio': 0.0,
        'row_count': 0,
        'date_count': 0,
        'ticker_count': 0,
        'evaluation_plan': evaluation_plan,
        'evaluation_results': {'backend_runs': backend_runs},
        'key_warnings': warnings,
        'failure_reason': failure_reason,
        'can_enter_step5': False,
        'recommended_step5_scope': None,
        'notes_for_step5': [f'Step 4 failed at {failed_stage}; do not evaluate.']
    }
    return run_master, diagnostics, handoff


def main() -> None:
    global FACTORFORGE, WORKSPACE, OBJ, RUNS
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id')
    ap.add_argument('--manifest', help='Runtime context manifest built by the skill/agent orchestrator.')
    ap.add_argument('--enable-shared-evaluation-context', action='store_true')
    args = ap.parse_args()
    enforce_direct_step_policy(args.manifest)
    manifest: dict[str, Any] | None = load_runtime_manifest(args.manifest) if args.manifest else None
    if manifest:
        FACTORFORGE = manifest_factorforge_root(manifest)
        WORKSPACE = FACTORFORGE.parent
        OBJ = FACTORFORGE / 'objects'
        RUNS = FACTORFORGE / 'runs'
    report_id = args.report_id or (manifest_report_id(manifest) if manifest else None)
    if not report_id:
        raise SystemExit('run_step4.py requires --report-id or --manifest')
    manifest_path_arg = Path(args.manifest).expanduser() if args.manifest else None
    start_utc = utc_now()
    input_paths = resolve_input_paths(report_id, manifest=manifest)
    run_dir = RUNS / report_id
    ensure_dir(run_dir)

    issues: list[dict[str, Any]] = []
    warnings: list[str] = []
    fsm: dict[str, Any] = {}
    dpm: dict[str, Any] = {}
    handoff: dict[str, Any] = {}
    factor_id: str | None = None
    implementation_path: str | None = None

    try:
        missing = [name for name, path in input_paths.items() if not path.exists()]
        if missing:
            for name in missing:
                issues.append({'severity': 'error', 'code': 'MISSING_INPUT', 'message': f'missing required input: {name}', 'evidence': {'path': str(input_paths[name])}})
            run_master, diagnostics, handoff_out = build_failure_outputs(report_id, None, None, {}, run_dir, input_paths, issues, warnings, 'MISSING_REQUIRED_INPUT', 'input_resolution', start_utc)
            write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
            write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
            write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
            return

        fsm = load_json(input_paths['factor_spec_master'])
        dpm = load_json(input_paths['data_prep_master'])
        handoff = load_json(input_paths['handoff_to_step4'])
        base_identity = handoff.get('artifact_identity') or fsm.get('artifact_identity') or {}
        implementation_mode_decision = (
            handoff.get('implementation_mode_decision')
            or fsm.get('implementation_mode_decision')
            or {}
        )
        factor_id = fsm.get('factor_id')

        v_issues, v_warnings = validate_inputs(report_id, fsm, dpm, handoff, input_paths)
        issues.extend(v_issues)
        warnings.extend(v_warnings)
        implementation_path, path_notes = resolve_implementation_path(handoff, fsm)
        warnings.extend(path_notes)

        if implementation_path is None:
            issues.append({'severity': 'error', 'code': 'IMPLEMENTATION_PATH_MISSING', 'message': 'implementation path unresolved', 'evidence': {'resolution_order': ['handoff_to_step4', 'factor_spec_master']}})
            run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, None, dpm.get('sample_window', {}), run_dir, input_paths, issues, warnings, 'IMPLEMENTATION_PATH_MISSING', 'implementation_resolution', start_utc)
            write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
            write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
            write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
            return

        if issues:
            run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, implementation_path, dpm.get('sample_window', {}), run_dir, input_paths, issues, warnings, 'INPUT_VALIDATION_FAILED', 'input_validation', start_utc)
            write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
            write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
            write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
            return

        impl_path = Path(implementation_path)
        if not impl_path.is_absolute():
            impl_path = (FACTORFORGE / impl_path) if str(implementation_path).startswith('generated_code/') else (WORKSPACE / implementation_path)
        if not impl_path.exists():
            issues.append({'severity': 'error', 'code': 'IMPLEMENTATION_PATH_NOT_FOUND', 'message': 'resolved implementation path does not exist', 'evidence': {'path': str(impl_path)}})
            run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, str(impl_path), dpm.get('sample_window', {}), run_dir, input_paths, issues, warnings, 'IMPLEMENTATION_PATH_NOT_FOUND', 'implementation_resolution', start_utc)
            write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
            write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
            write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
            return
        base_identity = fill_runtime_implementation_identity(base_identity, fsm, impl_path)

        # Frozen-schema execution: Step4 consumes either legacy normalized local
        # snapshots or the Step3 Data API contract. It must not guess raw paths or
        # build clean layers itself.
        local_inputs = handoff.get('local_input_paths') or dpm.get('local_input_paths') or {}
        step4_contract = _step4_data_contract(dpm, handoff)
        force_contract_inputs = bool((step4_contract.get('full_queries') or {}) if isinstance(step4_contract, dict) else False)
        minute_path = local_inputs.get('minute_df_parquet') or local_inputs.get('minute_df_csv')
        minute_streaming_query = (
            local_inputs.get('minute_streaming_query')
            if isinstance(local_inputs.get('minute_streaming_query'), dict)
            else None
        )
        daily_path = (
            local_inputs.get('daily_df_parquet')
            or local_inputs.get('daily_df_csv')
            or str(manifest_path(manifest, 'runs', 'step3a_daily_input_csv') or '')
        )
        input_mode = str(local_inputs.get('input_mode') or '')
        minute_required = input_mode != 'daily_only'
        if force_contract_inputs or (minute_required and (not minute_path or not daily_path)) or ((not minute_required) and not daily_path):
            try:
                contract_inputs, data_api_profile = materialize_step4_data_inputs_from_contract(
                    report_id,
                    step4_contract,
                    run_dir,
                )
            except SystemExit as exc:
                issues.append({
                    'severity': 'error',
                    'code': 'STEP4_DATA_INPUTS_MISSING',
                    'message': str(exc),
                    'evidence': {
                        'local_input_paths': local_inputs,
                        'step4_data_contract': _step4_data_contract(dpm, handoff),
                    },
                })
                run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, str(impl_path), dpm.get('sample_window', {}), run_dir, input_paths, issues, warnings, 'STEP4_DATA_INPUTS_MISSING', 'execution_precheck', start_utc)
                write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
                write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
                write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
                return
            local_inputs = {**local_inputs, **contract_inputs}
            minute_path = local_inputs.get('minute_df_parquet') or local_inputs.get('minute_df_csv')
            minute_streaming_query = (
                local_inputs.get('minute_streaming_query')
                if isinstance(local_inputs.get('minute_streaming_query'), dict)
                else None
            )
            daily_path = local_inputs.get('daily_df_parquet') or local_inputs.get('daily_df_csv')
            input_mode = str(local_inputs.get('input_mode') or '')
            minute_required = input_mode != 'daily_only'
        else:
            data_api_profile = None

        import pandas as pd  # local import to keep hard dependency only for real execution path
        minute_file = Path(minute_path) if minute_path else None
        daily_file = Path(daily_path)
        if minute_file is not None and not minute_file.is_absolute():
            minute_file = WORKSPACE / minute_file
        if not daily_file.is_absolute():
            daily_file = WORKSPACE / daily_file
        if (minute_required and minute_file is not None and not minute_file.exists()) or not daily_file.exists():
            issues.append({'severity': 'error', 'code': 'LOCAL_INPUT_FILES_NOT_FOUND', 'message': 'declared local input files do not exist', 'evidence': {'minute': str(minute_file) if minute_file else None, 'daily': str(daily_file)}})
            run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, str(impl_path), dpm.get('sample_window', {}), run_dir, input_paths, issues, warnings, 'LOCAL_INPUT_FILES_NOT_FOUND', 'execution_precheck', start_utc)
            write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
            write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
            write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
            return

        def read_df(p: Path):
            if p.suffix.lower() == '.parquet':
                return pd.read_parquet(p)
            return pd.read_csv(p)

        parquet_path = run_dir / f'factor_values__{report_id}.parquet'
        csv_path = run_dir / f'factor_values__{report_id}.csv'
        sample_csv_path = run_dir / f'factor_values_sample__{report_id}.csv'
        meta_path = run_dir / f'run_metadata__{report_id}.json'
        step3b_cache_path = run_dir / f'step3b_sample_factor_values__{report_id}.parquet'
        step3b_cache_meta_path = run_dir / f'step3b_sample_run_metadata__{report_id}.json'
        existing_meta = load_json(meta_path) if meta_path.exists() else {}
        factor_csv_policy_observed = step4_factor_csv_policy_from_step3b(existing_meta)
        parquet_existed_before_step4 = parquet_path.exists()
        existing_factor_source = classify_existing_factor_parquet_source(existing_meta) if parquet_existed_before_step4 else {}
        may_reuse_existing_factor = parquet_existed_before_step4 and existing_factor_source.get('source') == 'prior_step4_parquet'

        minute_df = read_df(minute_file) if minute_file is not None else pd.DataFrame()
        evaluation_daily_file = Path(local_inputs.get('evaluation_daily_df_parquet') or daily_file)
        if not evaluation_daily_file.is_absolute():
            evaluation_daily_file = WORKSPACE / evaluation_daily_file
        signal_daily_file = Path(local_inputs.get('signal_daily_df_parquet') or daily_file)
        if not signal_daily_file.is_absolute():
            signal_daily_file = WORKSPACE / signal_daily_file
        daily_df = read_df(evaluation_daily_file)
        signal_daily_df = read_df(signal_daily_file)
        expected_reuse_identity = build_step4_reuse_identity(
            report_id=report_id,
            factor_id=factor_id,
            base_identity=base_identity,
            dpm=dpm,
            daily_df=signal_daily_df,
        )
        existing_factor_reuse_gate = None
        if parquet_existed_before_step4:
            existing_factor_identity = (existing_meta.get('step4_formal_factor_identity') or existing_meta.get('step3b_compute_cache_identity') or existing_meta)
            existing_factor_reuse_gate = evaluate_reuse_gate(
                existing_factor_identity,
                expected_reuse_identity,
                source_artifact=str(parquet_path),
            )
            if existing_factor_source.get('source') == 'prior_step4_parquet':
                existing_factor_reuse_gate, _ = apply_artifact_binding_to_reuse_gate(
                    existing_factor_reuse_gate,
                    existing_factor_identity,
                    str(parquet_path),
                )
            if existing_factor_source.get('source') == 'step3b_sample_or_legacy_factor_parquet':
                existing_factor_reuse_gate['decision'] = 'block_invalid_formal_reuse'
                existing_factor_reuse_gate['reason'] = 'step3b_sample_proof_not_formal_factor_values'
        if may_reuse_existing_factor and existing_factor_reuse_gate and existing_factor_reuse_gate.get('decision') != 'reuse_allowed':
            may_reuse_existing_factor = False
        input_io_profile = {
            'source': 'local_snapshot' if data_api_profile is None else 'factorforge_data_api_full_query',
            'daily_selected_format': 'parquet' if daily_file.suffix.lower() == '.parquet' else 'csv',
            'daily_selected_path': str(daily_file),
            'formula_input_dataset': local_inputs.get('formula_input_dataset') or 'clean_daily_bar',
            'signal_daily_path': str(signal_daily_file),
            'evaluation_daily_path': str(evaluation_daily_file),
            'daily_parquet_path': str(WORKSPACE / local_inputs['daily_df_parquet']) if local_inputs.get('daily_df_parquet') and not Path(local_inputs['daily_df_parquet']).is_absolute() else local_inputs.get('daily_df_parquet'),
            'daily_csv_path': str(WORKSPACE / local_inputs['daily_df_csv']) if local_inputs.get('daily_df_csv') and not Path(local_inputs['daily_df_csv']).is_absolute() else local_inputs.get('daily_df_csv'),
            'data_api_profile': data_api_profile,
            'minute_streaming_enabled': bool(minute_streaming_query),
        }
        if isinstance(data_api_profile, dict):
            result_metadata = data_api_profile.get('result_metadata') if isinstance(data_api_profile.get('result_metadata'), dict) else {}
            daily_basic_meta = result_metadata.get('daily_basic') if isinstance(result_metadata.get('daily_basic'), dict) else {}
            daily_basic_perf = daily_basic_meta.get('performance_profile') if isinstance(daily_basic_meta.get('performance_profile'), dict) else {}
            backtest_base_profile = (
                data_api_profile.get('backtest_base_reuse_profile')
                if isinstance(data_api_profile.get('backtest_base_reuse_profile'), dict)
                else result_metadata.get('backtest_base_daily_controls_v1')
            )
            if isinstance(daily_basic_perf, dict) and daily_basic_perf:
                input_io_profile['daily_basic_reuse_profile'] = daily_basic_perf
                input_io_profile['daily_basic_selected_format'] = daily_basic_perf.get('daily_basic_selected_format')
                input_io_profile['daily_basic_cache_hit'] = daily_basic_perf.get('daily_basic_cache_hit')
                input_io_profile['daily_basic_cache_path'] = daily_basic_perf.get('daily_basic_cache_path')
                input_io_profile['daily_basic_rows'] = daily_basic_perf.get('daily_basic_rows')
                input_io_profile['daily_basic_dates'] = daily_basic_perf.get('daily_basic_dates')
                input_io_profile['daily_basic_tickers'] = daily_basic_perf.get('daily_basic_tickers')
                input_io_profile['daily_basic_load_seconds'] = daily_basic_perf.get('daily_basic_load_seconds')
            if isinstance(backtest_base_profile, dict) and backtest_base_profile:
                input_io_profile['backtest_base_reuse_profile'] = backtest_base_profile
                input_io_profile['backtest_base_reuse_hit'] = backtest_base_profile.get('backtest_base_reuse_hit')
                input_io_profile['backtest_base_cache_path'] = backtest_base_profile.get('backtest_base_cache_path')
        step3b_cache_source = {}
        if not may_reuse_existing_factor and step3b_cache_path.exists() and step3b_cache_meta_path.exists():
            step3b_cache_source = classify_step3b_compute_cache_source(
                load_json(step3b_cache_meta_path),
                signal_daily_df,
                impl_path,
                expected_identity=expected_reuse_identity,
                source_artifact=str(step3b_cache_path),
            )
        if may_reuse_existing_factor:
            result_df = read_df(parquet_path)
            step4_factor_io_profile = {
                'version': 'factorforge_step4_factor_io_profile_v1',
                **existing_factor_source,
                'selected_factor_format': 'parquet',
                'selected_factor_path': str(parquet_path),
                'recomputed_factor': False,
                'parquet_existed_before_step4': True,
                'parquet_written_by_step4': False,
                'reuse_gate': existing_factor_reuse_gate,
            }
        elif step3b_cache_source.get('reusable') is True:
            result_df = read_df(step3b_cache_path)
            step4_factor_io_profile = {
                'version': 'factorforge_step4_factor_io_profile_v1',
                **step3b_cache_source,
                'selected_factor_format': 'parquet',
                'selected_factor_path': str(step3b_cache_path),
                'formal_factor_path': str(parquet_path),
                'recomputed_factor': False,
                'parquet_existed_before_step4': bool(parquet_existed_before_step4),
                'parquet_written_by_step4': True,
                'reuse_gate': step3b_cache_source.get('reuse_gate'),
            }
        else:
            module = import_module_from_path(impl_path)
            if not hasattr(module, 'compute_factor'):
                issues.append({'severity': 'error', 'code': 'COMPUTE_FACTOR_MISSING', 'message': 'implementation module missing compute_factor', 'evidence': {'path': str(impl_path)}})
                run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, str(impl_path), dpm.get('sample_window', {}), run_dir, input_paths, issues, warnings, 'COMPUTE_FACTOR_MISSING', 'implementation_import', start_utc)
                write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
                write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
                write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
                return
            minute_streaming_profile = None
            intraday_flow_preagg_profile = None
            minute_derived_state_profile = None
            minute_derived_factor_profile = None
            if minute_streaming_query:
                try:
                    flow_requirement = _minute_flow_state_requirement(step4_contract, dpm)
                    minute_dates = _daily_trade_dates_for_minute_query(signal_daily_df, minute_streaming_query)
                    if flow_requirement:
                        flow_dataset_id = str(flow_requirement.get('dataset_id') or MINUTE_DERIVED_FLOW_STATE_V1)
                        if flow_dataset_id != MINUTE_DERIVED_FLOW_STATE_V1:
                            result_df, minute_derived_state_profile, minute_derived_factor_profile = (
                                compute_factor_from_data_api_minute_derived_state_batches(
                                    module,
                                    daily_df=signal_daily_df,
                                    requirement=flow_requirement,
                                    minute_query=minute_streaming_query,
                                )
                            )
                        else:
                            load_started = time.perf_counter()
                            flow_state_df, minute_derived_state_profile = _load_required_minute_flow_state(
                                requirement=flow_requirement,
                                daily_df=signal_daily_df,
                                minute_query=minute_streaming_query,
                            )
                            minute_derived_state_profile['phase_seconds'] = {
                                'load_derived_state': minute_derived_state_profile.get('load_seconds') or (time.perf_counter() - load_started),
                            }
                            result_df, minute_derived_factor_profile = compute_factor_from_minute_derived_state(
                                module,
                                daily_df=signal_daily_df,
                                flow_state_df=flow_state_df,
                                dataset_id=flow_dataset_id,
                            )
                    elif _generic_minute_full_window_forbidden(minute_dates):
                        raise SystemExit(
                            'BLOCK_STEP4_MINUTE_GENERIC_STREAMING_FULL_WINDOW_FORBIDDEN: '
                            f'generic minute streaming is forbidden for {len(minute_dates)} formal dates without '
                            f'{MINUTE_DERIVED_FLOW_STATE_V1}; run scripts/build_minute_derived_datamart.py or declare a derived-state contract.'
                        )
                    elif _supports_sp3_intraday_flow_fast_path(module):
                        result_df, intraday_flow_preagg_profile = compute_factor_intraday_flow_daily_preagg_contract(
                            daily_df=signal_daily_df,
                            minute_query=minute_streaming_query,
                            report_id=report_id,
                            run_dir=run_dir,
                        )
                    else:
                        result_df, minute_streaming_profile = compute_factor_streaming_minute_contract(
                            module,
                            daily_df=signal_daily_df,
                            minute_query=minute_streaming_query,
                            report_id=report_id,
                        )
                except SystemExit as exc:
                    token = str(exc).split(':', 1)[0]
                    issues.append({
                        'severity': 'error',
                        'code': token,
                        'message': str(exc),
                        'evidence': {
                            'minute_streaming_query': minute_streaming_query,
                            'minute_derived_state_requirements': _minute_derived_state_requirements(step4_contract, dpm),
                            'step4_data_contract': step4_contract,
                        },
                    })
                    run_master, diagnostics, handoff_out = build_failure_outputs(
                        report_id,
                        factor_id,
                        str(impl_path),
                        dpm.get('sample_window', {}),
                        run_dir,
                        input_paths,
                        issues,
                        warnings,
                        token,
                        'minute_derived_state_precheck',
                        start_utc,
                    )
                    write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
                    write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
                    write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
                    return
            else:
                result_df = compute_factor_with_contract(module, signal_daily_df, minute_df)
            step4_factor_io_profile = {
                'version': 'factorforge_step4_factor_io_profile_v1',
                'source': (
                    'step4_minute_derived_flow_state_recompute'
                    if minute_derived_state_profile else
                    'step4_intraday_flow_daily_preagg_recompute'
                    if intraday_flow_preagg_profile else
                    ('step4_minute_streaming_recompute' if minute_streaming_query else 'step4_recompute_fallback')
                ),
                'prior_factor_parquet_source': existing_factor_source.get('source') if parquet_existed_before_step4 else None,
                'step3b_compute_cache_source': step3b_cache_source or None,
                'selected_factor_format': 'computed',
                'selected_factor_path': str(parquet_path),
                'recomputed_factor': True,
                'parquet_existed_before_step4': bool(parquet_existed_before_step4),
                'parquet_written_by_step4': True,
                'reuse_gate': (
                    (step3b_cache_source or {}).get('reuse_gate')
                    or existing_factor_reuse_gate
                    or {
                        'version': 'factorforge_reuse_gate_v1',
                        'decision': 'recompute_required',
                        'matched_fields': [],
                        'mismatched_fields': [],
                        'missing_fields': [],
                        'source_artifact': str(parquet_path) if parquet_existed_before_step4 else None,
                        'reason': 'no_reusable_identity_matched',
                    }
                ),
            }
            if intraday_flow_preagg_profile:
                step4_factor_io_profile['intraday_flow_daily_preagg_profile'] = intraday_flow_preagg_profile
            if minute_derived_state_profile:
                step4_factor_io_profile['minute_derived_state_profile'] = minute_derived_state_profile
            if minute_derived_factor_profile:
                step4_factor_io_profile['minute_derived_factor_profile'] = minute_derived_factor_profile
                step4_factor_io_profile['performance_phase_profile'] = {
                    'load_derived_state_seconds': float((minute_derived_state_profile or {}).get('load_seconds') or 0.0),
                    'factor_compute_seconds': float(minute_derived_factor_profile.get('factor_compute_seconds') or 0.0),
                    'evaluation_seconds': None,
                    'write_outputs_seconds': None,
                }
            if minute_streaming_profile:
                step4_factor_io_profile['minute_streaming_profile'] = minute_streaming_profile

        if result_df is None or len(result_df) == 0:
            issues.append({'severity': 'error', 'code': 'EMPTY_MAIN_RESULT', 'message': 'main result not materially generated', 'evidence': {'rows': 0}})
            run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, str(impl_path), dpm.get('sample_window', {}), run_dir, input_paths, issues, warnings, 'EMPTY_MAIN_RESULT', 'execution', start_utc)
            write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
            write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
            write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
            return

        signal_col = infer_signal_column(result_df, factor_id=factor_id)
        if not may_reuse_existing_factor:
            result_df.to_parquet(parquet_path, index=False)
        if factor_csv_policy_observed.get('factor_csv_write_allowed') and not csv_path.exists():
            result_df.to_csv(csv_path, index=False)
            step4_factor_io_profile['csv_written_by_step4'] = True
        else:
            step4_factor_io_profile['csv_written_by_step4'] = False
        factor_csv_policy_observed['factor_csv_written_by_step4'] = bool(
            step4_factor_io_profile['csv_written_by_step4']
        )
        if factor_csv_policy_observed.get('factor_csv_write_allowed') and not step4_factor_io_profile['csv_written_by_step4']:
            factor_csv_policy_observed['factor_csv_write_skipped_reason'] = 'step3b_csv_already_available'

        row_count = int(len(result_df))
        date_count = int(result_df['trade_date'].nunique()) if 'trade_date' in result_df.columns else 0
        ticker_count = int(result_df['ts_code'].nunique()) if 'ts_code' in result_df.columns else 0
        actual_start = _normal_date_value(result_df['trade_date'].min()) if 'trade_date' in result_df.columns and row_count else None
        actual_end = _normal_date_value(result_df['trade_date'].max()) if 'trade_date' in result_df.columns and row_count else None
        target_window = dpm.get('sample_window', {}) or {}
        prepared_window = (dpm.get('local_input_paths') or {}).get('sample_window_actual') or {}
        research_window = _research_window_contract(step4_contract, dpm)
        target_start_raw = target_window.get('start')
        target_start = _normal_date_value(target_start_raw)
        target_end_raw = target_window.get('end')
        input_daily_start = _normal_date_value(signal_daily_df['trade_date'].min()) if 'trade_date' in signal_daily_df.columns and len(signal_daily_df) else None
        input_daily_end = _normal_date_value(signal_daily_df['trade_date'].max()) if 'trade_date' in signal_daily_df.columns and len(signal_daily_df) else None
        prepared_start = _normal_date_value(prepared_window.get('start'))
        prepared_end = _normal_date_value(prepared_window.get('end'))
        # Step3B sample snapshots may leave a short sample_window_actual in
        # data_prep_master. Once Step4 has materialized the formal Data API
        # full-query input, that sample window must not cap Step4 coverage.
        full_contract_input = bool(data_api_profile is not None and force_contract_inputs)
        if full_contract_input:
            effective_target_start = input_daily_start or target_start
            effective_target_end = input_daily_end if str(target_end_raw) == 'current' else (input_daily_end or _normal_date_value(target_end_raw))
        else:
            effective_target_start = prepared_start or input_daily_start or target_start
            if str(target_end_raw) == 'current':
                effective_target_end = input_daily_end
            else:
                effective_target_end = prepared_end or _normal_date_value(target_end_raw)
        target_end = effective_target_end
        coverage_complete = (actual_start == effective_target_start and actual_end == effective_target_end)
        run_status = 'success' if coverage_complete else 'partial'
        failure_reason = None
        sparse_signal_allowed = bool(
            step4_contract.get('sparse_signal_allowed')
            or dpm.get('sparse_signal_allowed')
            or handoff.get('sparse_signal_allowed')
        )
        formal_signal_coverage = build_formal_signal_coverage_profile(
            result_df=result_df,
            signal_col=signal_col,
            actual_start=actual_start,
            actual_end=actual_end,
            effective_target_start=effective_target_start,
            effective_target_end=effective_target_end,
            sparse_signal_allowed=sparse_signal_allowed,
        )
        if formal_signal_coverage.get('coverage_gate_verdict') == 'BLOCK':
            token = 'BLOCK_STEP4_FORMAL_SIGNAL_NON_NULL_COVERAGE_LOW'
            issues.append({
                'severity': 'error',
                'code': token,
                'message': 'formal Step4 factor values have insufficient non-null signal coverage for promotion-gate evidence',
                'evidence': formal_signal_coverage,
            })
            run_status = 'failed'
            failure_reason = token
        shared_context: dict[str, Any] | None = None
        shared_context_profile: dict[str, Any] = {
            'version': 'factorforge_shared_evaluation_context_v1',
            'enabled': False,
            'built': False,
            'used_by_step4': False,
            'context_path': None,
            'build_seconds': 0.0,
            'invalidated_reason': 'not_enabled',
        }
        force_shared_context = (
            data_api_profile is not None
            or str(local_inputs.get('formula_input_dataset') or 'clean_daily_bar') != 'clean_daily_bar'
        )
        if shared_evaluation_context_enabled(args.enable_shared_evaluation_context) or force_shared_context:
            shared_context = build_shared_evaluation_context(
                report_id=report_id,
                factor_id=factor_id,
                implementation_mode_decision=implementation_mode_decision,
                base_identity=base_identity,
                run_dir=run_dir,
                factor_df=result_df,
                daily_df=daily_df,
                signal_col=signal_col,
                factor_parquet_path=parquet_path,
                daily_input_path=evaluation_daily_file,
                target_window=target_window,
                effective_target_window={'start': effective_target_start, 'end': effective_target_end},
            )
            shared_context_profile = {
                'version': 'factorforge_shared_evaluation_context_v1',
                'enabled': True,
                'built': True,
                'used_by_step4': False,
                'context_path': ((shared_context.get('paths') or {}).get('context_json')),
                'build_seconds': shared_context.get('build_seconds'),
                'invalidated_reason': None,
                'row_counts': shared_context.get('row_counts'),
            }
        evaluation_plan = build_evaluation_plan(handoff)
        backend_runs = build_backend_runs_stub(report_id, evaluation_plan, run_status)
        backend_runs, backend_timing_profile = write_backend_payloads(
            report_id,
            backend_runs,
            manifest_path_arg=manifest_path_arg,
            shared_context=shared_context,
        )
        backend_timing_profile['shared_evaluation_context'] = {
            'enabled': bool(shared_context),
            'built': bool(shared_context),
            'build_seconds': shared_context_profile.get('build_seconds') if shared_context else 0.0,
            'context_path': shared_context_profile.get('context_path') if shared_context else None,
        }

        step4_owned_meta = {
            'report_id': report_id,
            'factor_id': factor_id,
            'implementation_mode_decision': implementation_mode_decision,
            'implementation_path': str(impl_path),
            'started_at_utc': start_utc,
            'finished_at_utc': utc_now(),
            'row_count': row_count,
            'date_count': date_count,
            'ticker_count': ticker_count,
            'signal_column': signal_col,
            'actual_window': {'start': actual_start, 'end': actual_end},
            'target_window': target_window,
            'effective_target_window': {'start': effective_target_start, 'end': effective_target_end},
            'run_status_candidate': run_status,
            'input_io_profile': input_io_profile,
            'step4_factor_io_profile': step4_factor_io_profile,
            'formal_signal_coverage': formal_signal_coverage,
            'step4_formal_factor_identity': expected_reuse_identity,
            'step4_factor_csv_policy_observed': factor_csv_policy_observed,
            'shared_evaluation_context': shared_context_profile,
            'backend_timing_profile': backend_timing_profile,
            'research_window_contract': research_window,
        }
        meta = merge_run_metadata(existing_meta, step4_owned_meta)
        write_json(meta_path, meta)
        step4_output_paths = output_paths_for_policy(parquet_path, csv_path, sample_csv_path, meta_path, factor_csv_policy_observed)

        run_master_path = OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json'
        diag_path = OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json'
        handoff_path = OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json'

        run_master = {
            'report_id': report_id,
            'factor_id': factor_id,
            'artifact_identity': derive_identity(base_identity, 'factor_run_master'),
            'run_status': run_status,
            'implementation_path': str(impl_path),
            'output_paths': step4_output_paths,
            'sample_window': target_window,
            'runtime_notes': warnings,
            'diagnostic_summary': {'row_count': row_count, 'date_count': date_count, 'ticker_count': ticker_count},
            'signal_column': signal_col,
            'evaluation_plan': evaluation_plan,
            'evaluation_results': {'backend_runs': backend_runs},
            'backend_timing_profile': backend_timing_profile,
            'shared_evaluation_context': shared_context_profile,
            'implementation_mode_decision': implementation_mode_decision,
            'failure_reason': failure_reason,
            'started_at_utc': start_utc,
            'finished_at_utc': utc_now(),
            'input_paths': {k: str(v) for k, v in input_paths.items()},
            'input_io_profile': input_io_profile,
            'window_coverage': {
                'target_start': target_window.get('start'),
                'target_end': target_window.get('end'),
                'effective_target_start': effective_target_start,
                'effective_target_end': effective_target_end,
                'input_daily_start': input_daily_start,
                'input_daily_end': input_daily_end,
                'actual_start': actual_start,
                'actual_end': actual_end,
                'coverage_complete': coverage_complete,
            },
            'formal_signal_coverage': formal_signal_coverage,
            'validation_pointer': str(diag_path),
            'handoff_to_step5_path': str(handoff_path),
        }

        null_ratio = {}
        for col in [signal_col]:
            if col in result_df.columns and row_count:
                null_ratio[col] = float(result_df[col].isna().mean())
        duplicate_ratio = {}
        if {'ts_code', 'trade_date'}.issubset(result_df.columns):
            duplicate_ratio['ts_code_trade_date'] = float(result_df.duplicated(['ts_code', 'trade_date']).mean())
        sort_order_ok = True
        if {'ts_code', 'trade_date'}.issubset(result_df.columns):
            sort_order_ok = result_df[['ts_code', 'trade_date']].reset_index(drop=True).equals(
                result_df.sort_values(['ts_code', 'trade_date'])[['ts_code', 'trade_date']].reset_index(drop=True)
            )

        diagnostics = {
            'report_id': report_id,
            'factor_id': factor_id,
            'run_status': run_status,
            'diagnostic_generated_at_utc': utc_now(),
            'evaluation_plan': evaluation_plan,
            'evaluation_results': {'backend_runs': backend_runs},
            'implementation_mode_decision': implementation_mode_decision,
            'input_validation': {
                'exists_check': {k: v.exists() for k, v in input_paths.items()},
                'input_io_profile': input_io_profile,
                'step4_factor_io_profile': step4_factor_io_profile,
                'step4_factor_csv_policy_observed': factor_csv_policy_observed,
                'backend_timing_profile': backend_timing_profile,
                'shared_evaluation_context': shared_context_profile,
                'schema_check': {'frozen_schema_execution': True},
                'consistency_check': {
                    'report_id_consistent': True,
                    'factor_id_consistent': True
                },
                'placeholder_check': {
                    'factor_spec_master_has_placeholder': contains_placeholder(fsm),
                    'data_prep_master_has_placeholder': contains_placeholder(dpm),
                    'handoff_to_step4_has_placeholder': contains_placeholder(handoff)
                }
            },
            'execution_trace': {
                'implementation_path': str(impl_path),
                'commands': [f'python3 skills/factor-forge-step4/scripts/run_step4.py --report-id {report_id}'],
                'runtime_seconds': None,
                'exception_type': None,
                'exception_message': None
            },
            'output_validation': {
                'output_exists': True,
                'output_paths': step4_output_paths,
                'file_sizes': file_sizes_for_paths(step4_output_paths),
                'row_count': row_count,
                'date_count': date_count,
                'ticker_count': ticker_count,
                'signal_column': signal_col,
                'formal_signal_coverage': formal_signal_coverage,
            },
            'quality_checks': {
                'window_complete': coverage_complete,
                'null_ratio': null_ratio,
                'formal_signal_coverage': formal_signal_coverage,
                'duplicate_ratio': duplicate_ratio,
                'key_uniqueness': {'ts_code_trade_date_unique': duplicate_ratio.get('ts_code_trade_date', 0.0) == 0.0},
                'sort_order_ok': sort_order_ok
            },
            'issues': issues,
            'failure_context': {
                'failed_stage': None,
                'failure_reason': None,
                'retryable': False
            },
            'recommendation': {
                'can_handoff_to_step5': run_status in {'success', 'partial'},
                'recommended_status': run_status,
                'next_action': (
                    'Proceed to Step 5 using declared evaluation scope.'
                    if run_status in {'success', 'partial'}
                    else 'Fix formal signal coverage and rerun Step 4 before Step 5/6.'
                )
            }
        }

        # COMMENT_POLICY: execution_handoff
        # Step 4 emits a stable handoff envelope for Step 5 to avoid implicit coupling.
        handoff_out = {
            'report_id': report_id,
            'factor_id': factor_id,
            'artifact_identity': derive_identity(base_identity, 'handoff_to_step5'),
            'run_status': run_status,
            'factor_run_master_path': str(run_master_path),
            'diagnostics_path': str(diag_path),
            'output_paths': step4_output_paths,
            'sample_window_target': target_window,
            'sample_window_actual': {'start': actual_start, 'end': actual_end},
            'coverage_ratio': 1.0 if coverage_complete else None,
            'row_count': row_count,
            'date_count': date_count,
            'ticker_count': ticker_count,
            'signal_column': signal_col,
            'evaluation_plan': evaluation_plan,
            'evaluation_results': {'backend_runs': backend_runs},
            'backend_timing_profile': backend_timing_profile,
            'shared_evaluation_context': shared_context_profile,
            'implementation_mode_decision': implementation_mode_decision,
            'key_warnings': warnings,
            'failure_reason': failure_reason,
            'can_enter_step5': run_status in {'success', 'partial'},
            'recommended_step5_scope': (
                'full'
                if run_status == 'success'
                else 'partial_scope_only'
                if run_status == 'partial'
                else None
            ),
            'notes_for_step5': (
                ['partial result: evaluate only covered window/instruments']
                if run_status == 'partial'
                else ['full result ready for evaluation']
                if run_status == 'success'
                else ['Step4 formal signal coverage failed; do not evaluate or promote.']
            )
        }

        acceptance_summary = build_acceptance_summary(
            report_id=report_id,
            factor_id=factor_id,
            run_status=run_status,
            output_paths=step4_output_paths,
            backend_runs=backend_runs,
            backend_timing_profile=backend_timing_profile,
            step4_factor_io_profile=step4_factor_io_profile,
            input_io_profile=input_io_profile,
        )
        run_master = add_formal_acceptance_envelope(
            run_master,
            identity=run_master['artifact_identity'],
            run_status=run_status,
            acceptance_summary=acceptance_summary,
        )
        handoff_out = add_formal_acceptance_envelope(
            handoff_out,
            identity=handoff_out['artifact_identity'],
            run_status=run_status,
            acceptance_summary=acceptance_summary,
        )

        write_json(run_master_path, run_master)
        write_json(diag_path, diagnostics)
        write_json(handoff_path, handoff_out)
    except Exception as e:
        issues.append({'severity': 'error', 'code': 'UNHANDLED_EXCEPTION', 'message': str(e), 'evidence': {'traceback': traceback.format_exc()[-4000:]}})
        run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, implementation_path, dpm.get('sample_window', {}) if dpm else {}, run_dir, input_paths, issues, warnings, type(e).__name__, 'unhandled_exception', start_utc)
        diagnostics['execution_trace']['exception_type'] = type(e).__name__
        diagnostics['execution_trace']['exception_message'] = str(e)
        diagnostics['issues'] = issues
        write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
        write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
        write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
        raise


if __name__ == '__main__':
    main()
