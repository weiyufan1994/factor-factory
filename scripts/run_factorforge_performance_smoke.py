#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.formula.operators import resolve_ts_rank_engine, ts_rank
from factor_factory.formula.evaluator import evaluate_formula_frame, evaluate_formula_ir, evaluate_formula_ir_optimized
from factor_factory.formula.fast_rolling import ts_rank_reference
from factor_factory.formula.parser import parse_formula
from factor_factory.formula.pandas_codegen import generate_pandas_formula_code
from factor_factory.formula.polars_evaluator import assert_polars_result_parity, polars_dependency_available
from factor_factory.formula.ts_rank_candidates import available_candidates, compare_candidate_to_reference, prepare_ts_rank_frame
from factor_factory.formula.kernels import DEFAULT_NUMPY_TS_EXCLUDED_OPERATORS, DEFAULT_NUMPY_TS_OPERATORS, resolve_formula_kernel_engine
from factor_factory.factor_families.price_volume import PLUGIN as PRICE_VOLUME_PLUGIN

CANONICAL_DIRS = ['objects', 'runs', 'evaluations', 'generated_code', 'archive', 'factorforge', 'data/clean']


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def tail(text: str, limit: int = 4000) -> str:
    return text[-limit:] if len(text) > limit else text


def snapshot_repo_files() -> set[str]:
    files: set[str] = set()
    for rel in CANONICAL_DIRS:
        root = REPO_ROOT / rel
        if not root.exists():
            continue
        if root.is_file():
            files.add(str(root.relative_to(REPO_ROOT)))
            continue
        for path in root.rglob('*'):
            if path.is_file():
                files.add(str(path.relative_to(REPO_ROOT)))
    return files


def run_cmd(cmd: list[str], *, root: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if root is not None:
        env['FACTORFORGE_ROOT'] = str(root)
    return subprocess.run(cmd, cwd=REPO_ROOT, env=env, text=True, capture_output=True)


@contextmanager
def temporary_env(name: str, value: str | None):
    old = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old


@contextmanager
def temporary_envs(values: dict[str, str | None]):
    old_values = {name: os.environ.get(name) for name in values}
    for name, value in values.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    try:
        yield
    finally:
        for name, old in old_values.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old


def build_operator_parity_frame() -> pd.DataFrame:
    rows = []
    for code in ['A', 'B', 'C']:
        for i in range(30):
            value = float((i * 7) % 11)
            if code == 'B' and i in {5, 6, 7}:
                value = 3.0
            if code == 'C' and i == 12:
                value = np.nan
            rows.append({'ts_code': code, 'trade_date': f'202001{i+1:02d}', 'x': value})
    return pd.DataFrame(rows)


def reference_ts_rank(series: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return series.groupby(frame['ts_code'], sort=False).transform(
        lambda s: s.rolling(window, min_periods=window).apply(
            lambda values: pd.Series(values).rank(method='average', pct=True).iloc[-1],
            raw=False,
        )
    )


def run_py_compile() -> dict[str, Any]:
    cmd = [
        sys.executable,
        '-m',
        'py_compile',
        'factor_factory/performance/__init__.py',
        'factor_factory/performance/timing.py',
        'factor_factory/formula/operators.py',
        'factor_factory/formula/evaluator.py',
        'factor_factory/formula/fast_rolling.py',
        'factor_factory/formula/profiling.py',
        'factor_factory/formula/polars_evaluator.py',
        'factor_factory/formula/ts_rank_candidates.py',
        'factor_factory/formula/operator_candidate_benchmarks.py',
        'factor_factory/formula/kernels.py',
        'factor_factory/data_access/__init__.py',
        'factor_factory/data_access/step4.py',
        'skills/factor-forge-step3/scripts/run_step3.py',
        'skills/factor-forge-step3/scripts/validate_step3.py',
        'skills/factor-forge-step3/scripts/run_step3b.py',
        'skills/factor-forge-step4/scripts/run_step4.py',
        'skills/factor-forge-step4/scripts/self_quant_adapter.py',
        'skills/factor-forge-step4/scripts/validate_step4.py',
        'scripts/run_factorforge_performance_profile.py',
        'scripts/run_factorforge_operator_kernel_inventory.py',
        'scripts/run_factorforge_operator_candidate_benchmark.py',
        'scripts/run_factorforge_throughput_profile.py',
        'scripts/run_ts_rank_candidate_benchmark.py',
        'scripts/run_factorforge_performance_smoke.py',
    ]
    proc = run_cmd(cmd)
    return {'case': 'py_compile', 'rc': proc.returncode, 'ok': proc.returncode == 0, 'stdout_tail': tail(proc.stdout), 'stderr_tail': tail(proc.stderr)}


def run_operator_parity() -> dict[str, Any]:
    frame = build_operator_parity_frame()
    actual = ts_rank(frame['x'], 5, frame)
    expected = reference_ts_rank(frame['x'], 5, frame)
    ok = bool(np.allclose(actual.fillna(-9999), expected.fillna(-9999), atol=1e-12))
    return {
        'case': 'operator_ts_rank_parity',
        'ts_rank_parity': ok,
        'max_abs_diff': float(np.nanmax(np.abs(actual.fillna(-9999).to_numpy() - expected.fillna(-9999).to_numpy()))),
        'ok': ok,
    }


def import_run_step3b(root: Path):
    os.environ['FACTORFORGE_ROOT'] = str(root)
    path = REPO_ROOT / 'skills' / 'factor-forge-step3' / 'scripts' / 'run_step3b.py'
    spec = importlib.util.spec_from_file_location('run_step3b_perf_smoke', path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot import {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def import_run_step3(root: Path):
    os.environ['FACTORFORGE_ROOT'] = str(root)
    os.environ['ALLOW_SYNTHETIC_FALLBACK'] = '1'
    path = REPO_ROOT / 'skills' / 'factor-forge-step3' / 'scripts' / 'run_step3.py'
    spec = importlib.util.spec_from_file_location('run_step3_perf_smoke', path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot import {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def import_self_quant_adapter(root: Path):
    os.environ['FACTORFORGE_ROOT'] = str(root)
    path = REPO_ROOT / 'skills' / 'factor-forge-step4' / 'scripts' / 'self_quant_adapter.py'
    spec = importlib.util.spec_from_file_location('self_quant_perf_smoke', path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot import {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_step3b_fixture(root: Path, report_id: str) -> tuple[Path, dict[str, str]]:
    run_dir = root / 'runs' / report_id / 'step3a_local_inputs'
    run_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for code_idx in range(1, 6):
        for day in range(1, 8):
            rows.append({
                'ts_code': f'S{code_idx:03d}',
                'trade_date': f'202001{day:02d}',
                'close': 10.0 + code_idx + day,
                'pct_chg': float((code_idx - 3) * 0.1 + day * 0.01),
            })
    daily = pd.DataFrame(rows)
    daily_csv_path = run_dir / f'daily_input__{report_id}.csv'
    daily_parquet_path = run_dir / f'daily_input__{report_id}.parquet'
    daily.to_parquet(daily_parquet_path, index=False)
    daily.to_csv(daily_csv_path, index=False)
    impl_dir = root / 'generated_code' / report_id
    impl_dir.mkdir(parents=True, exist_ok=True)
    impl = impl_dir / 'factor_impl.py'
    impl.write_text(
        "def compute_factor(daily_df, minute_df=None):\n"
        "    out = daily_df[['ts_code', 'trade_date', 'close']].copy()\n"
        "    out['smoke_factor'] = out['close'].rank(pct=True)\n"
        "    return out[['ts_code', 'trade_date', 'smoke_factor']]\n",
        encoding='utf-8',
    )
    return impl, {
        'input_mode': 'daily_only',
        'daily_df_parquet': str(daily_parquet_path),
        'daily_df_csv': str(daily_csv_path),
        'preferred_daily_format': 'parquet',
        'audit_daily_format': 'csv',
        'daily_io_contract': {
            'version': 'factorforge_step3a_daily_io_contract_v1',
            'performance_path': 'parquet',
            'audit_path': 'csv',
            'csv_output_policy': 'full_csv',
            'csv_rows_written': int(len(daily)),
            'parquet_rows_written': int(len(daily)),
            'csv_sample_strategy': 'full',
            'full_csv_available': True,
            'schema_parity_required': True,
            'value_parity_required': True,
            'csv_required_for_audit': True,
            'parquet_required_for_performance': True,
        },
    }


def sort_contract_key_hash(df: pd.DataFrame) -> str:
    key_frame = df[['ts_code', 'trade_date']].astype(str).reset_index(drop=True)
    payload = key_frame.to_csv(index=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def attach_sort_contract(local_inputs: dict[str, Any], df: pd.DataFrame, *, mutate: str | None = None) -> dict[str, Any]:
    contract = {
        'version': 'factorforge_sort_contract_v1',
        'sorted_by': ['ts_code', 'trade_date'],
        'row_count': int(len(df)),
        'key_dtype': {
            'ts_code': str(df['ts_code'].dtype),
            'trade_date': str(df['trade_date'].dtype),
        },
        'source': 'step3a_local_input',
        'data_hash': sort_contract_key_hash(df),
        'duplicate_key_check': not bool(df[['ts_code', 'trade_date']].duplicated().any()),
        'sample_sortedness_check': True,
    }
    if mutate == 'row_count_mismatch':
        contract['row_count'] = int(len(df) + 1)
    if mutate == 'duplicate_key_detected':
        contract['duplicate_key_check'] = False
    out = dict(local_inputs)
    daily_contract = dict(out.get('daily_io_contract') or {})
    daily_contract['sort_contract'] = contract
    out['daily_io_contract'] = daily_contract
    out['sort_contract'] = contract
    return out


def create_step3b_sort_contract_fixture(
    root: Path,
    report_id: str,
    *,
    duplicate: bool = False,
    unsampled_inversion: bool = False,
    mutate_contract: str | None = None,
) -> tuple[Path, dict[str, Any], pd.DataFrame]:
    if unsampled_inversion:
        run_dir = root / 'runs' / report_id / 'step3a_local_inputs'
        run_dir.mkdir(parents=True, exist_ok=True)
        dates = pd.bdate_range(start='2020-01-02', periods=210)
        rows = []
        for code_idx in range(1, 31):
            for day, date in enumerate(dates, start=1):
                rows.append({
                    'ts_code': f'S{code_idx:04d}',
                    'trade_date': date.strftime('%Y%m%d'),
                    'close': 10.0 + code_idx + day * 0.001,
                    'pct_chg': float(code_idx * 0.0001 + day * 0.00001),
                })
        daily = pd.DataFrame(rows).sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
        # Swap two adjacent rows that the previous sparse sample missed when len ~= 6300.
        daily.iloc[[3001, 3002]] = daily.iloc[[3002, 3001]].to_numpy()
        daily_csv_path = run_dir / f'daily_input__{report_id}.csv'
        daily_parquet_path = run_dir / f'daily_input__{report_id}.parquet'
        daily.to_parquet(daily_parquet_path, index=False)
        daily.to_csv(daily_csv_path, index=False)
        impl_dir = root / 'generated_code' / report_id
        impl_dir.mkdir(parents=True, exist_ok=True)
        impl = impl_dir / 'factor_impl.py'
        impl.write_text(
            "def compute_factor(daily_df, minute_df=None):\n"
            "    out = daily_df[['ts_code', 'trade_date', 'close']].copy()\n"
            "    out['smoke_factor'] = out['close'].rank(pct=True)\n"
            "    return out[['ts_code', 'trade_date', 'smoke_factor']]\n",
            encoding='utf-8',
        )
        local_inputs = {
            'input_mode': 'daily_only',
            'daily_df_parquet': str(daily_parquet_path),
            'daily_df_csv': str(daily_csv_path),
            'preferred_daily_format': 'parquet',
            'audit_daily_format': 'csv',
            'daily_io_contract': {
                'version': 'factorforge_step3a_daily_io_contract_v1',
                'performance_path': 'parquet',
                'audit_path': 'csv',
                'csv_output_policy': 'full_csv',
                'csv_rows_written': int(len(daily)),
                'parquet_rows_written': int(len(daily)),
                'csv_sample_strategy': 'full',
                'full_csv_available': True,
                'schema_parity_required': True,
                'value_parity_required': True,
                'csv_required_for_audit': True,
                'parquet_required_for_performance': True,
            },
        }
    else:
        impl, local_inputs = create_step3b_fixture(root, report_id)
        daily = pd.read_parquet(Path(local_inputs['daily_df_parquet']))
    daily_path = Path(local_inputs['daily_df_parquet'])
    if duplicate:
        daily = pd.concat([daily.iloc[[0]], daily], ignore_index=True)
        daily.to_parquet(daily_path, index=False)
        daily.to_csv(Path(local_inputs['daily_df_csv']), index=False)
    local_inputs = attach_sort_contract(local_inputs, daily, mutate=mutate_contract)
    return impl, local_inputs, daily


def run_step3b_sort_contract_case(
    root: Path,
    report_id: str,
    *,
    trust: bool,
    duplicate: bool = False,
    unsampled_inversion: bool = False,
    mutate_contract: str | None = None,
) -> dict[str, Any]:
    impl, local_inputs, daily = create_step3b_sort_contract_fixture(
        root,
        report_id,
        duplicate=duplicate,
        unsampled_inversion=unsampled_inversion,
        mutate_contract=mutate_contract,
    )
    module = import_run_step3b(root)
    env = {'FACTORFORGE_TRUST_STEP3A_SORT_CONTRACT': '1' if trust else None}
    with temporary_envs(env):
        try:
            kwargs = {
                'report_id': report_id,
                'factor_id': 'SMOKE',
                'implementation_path': impl,
                'local_inputs': local_inputs,
                'step2_research_context': {'smoke': True},
                'mode_decision': {'implementation_mode': 'direct_code'},
                'artifact_identity': {},
            }
            if 'trust_step3a_sort_contract' in module.generate_first_run_factor_values.__code__.co_varnames:
                kwargs['trust_step3a_sort_contract'] = trust
            outputs = module.generate_first_run_factor_values(**kwargs)
            metadata = read_json(root / outputs['run_metadata_path'])
            values = pd.read_parquet(root / outputs['output_paths'][0])
            return {'rc': 0, 'metadata': metadata, 'values': values, 'daily': daily, 'error': None}
        except SystemExit as exc:
            return {'rc': 1, 'metadata': {}, 'values': pd.DataFrame(), 'daily': daily, 'error': str(exc)}


def run_sort_contract_written_by_step3a_case(root: Path) -> dict[str, Any]:
    report_id = 'STEP_PERF_SORT_CONTRACT'
    module = import_run_step3(root)
    local_inputs = module.build_local_price_volume_snapshots(report_id, {'start': '20160104', 'end': '20160329'})
    contract = (local_inputs.get('daily_io_contract') or {}).get('sort_contract') or local_inputs.get('sort_contract') or {}
    ok = (
        contract.get('version') == 'factorforge_sort_contract_v1'
        and contract.get('sorted_by') == ['ts_code', 'trade_date']
        and int(contract.get('row_count') or 0) > 0
        and isinstance(contract.get('data_hash'), str)
        and len(contract.get('data_hash') or '') >= 32
        and contract.get('duplicate_key_check') is True
        and contract.get('sample_sortedness_check') is True
    )
    return {'case': 'sort_contract_written_by_step3a', 'report_id': report_id, 'sort_contract': contract, 'ok': bool(ok)}


def run_step3b_trusted_sort_contract_skips_full_sort_opt_in_case(root: Path) -> dict[str, Any]:
    result = run_step3b_sort_contract_case(root, 'PERF_SMOKE_SORT_CONTRACT_TRUSTED', trust=True)
    profile = (((result.get('metadata') or {}).get('performance_profile') or {}).get('normalize_sort_profile') or {})
    ok = (
        result.get('rc') == 0
        and profile.get('version') == 'factorforge_normalize_sort_profile_v1'
        and profile.get('sort_contract_present') is True
        and profile.get('sort_contract_trusted') is True
        and profile.get('full_sort_skipped') is True
        and profile.get('full_sort_skipped_reason') == 'trusted_step3a_sort_contract'
    )
    return {'case': 'step3b_trusted_sort_contract_skips_full_sort_opt_in', 'normalize_sort_profile': profile, 'ok': bool(ok)}


def run_step3b_sort_contract_default_path_unchanged_without_opt_in_case(root: Path) -> dict[str, Any]:
    result = run_step3b_sort_contract_case(root, 'PERF_SMOKE_SORT_CONTRACT_DEFAULT', trust=False)
    profile = (((result.get('metadata') or {}).get('performance_profile') or {}).get('normalize_sort_profile') or {})
    ok = (
        result.get('rc') == 0
        and profile.get('sort_contract_present') is True
        and profile.get('sort_contract_trusted') is False
        and profile.get('full_sort_skipped') is False
        and profile.get('fallback_reason') == 'opt_in_disabled'
    )
    return {'case': 'step3b_sort_contract_default_path_unchanged_without_opt_in', 'normalize_sort_profile': profile, 'ok': bool(ok)}


def run_step3b_sort_contract_fallback_on_row_count_mismatch_case(root: Path) -> dict[str, Any]:
    result = run_step3b_sort_contract_case(root, 'PERF_SMOKE_SORT_CONTRACT_ROW_MISMATCH', trust=True, mutate_contract='row_count_mismatch')
    profile = (((result.get('metadata') or {}).get('performance_profile') or {}).get('normalize_sort_profile') or {})
    ok = (
        result.get('rc') == 0
        and profile.get('sort_contract_trusted') is False
        and profile.get('full_sort_skipped') is False
        and profile.get('fallback_reason') == 'row_count_mismatch'
    )
    return {'case': 'step3b_sort_contract_fallback_on_row_count_mismatch', 'normalize_sort_profile': profile, 'ok': bool(ok)}


def run_step3b_sort_contract_fallback_on_duplicate_key_case(root: Path) -> dict[str, Any]:
    result = run_step3b_sort_contract_case(root, 'PERF_SMOKE_SORT_CONTRACT_DUPLICATE', trust=True, duplicate=True, mutate_contract='duplicate_key_detected')
    profile = (((result.get('metadata') or {}).get('performance_profile') or {}).get('normalize_sort_profile') or {})
    ok = (
        result.get('rc') == 0
        and profile.get('sort_contract_trusted') is False
        and profile.get('full_sort_skipped') is False
        and profile.get('fallback_reason') == 'duplicate_key_detected'
    )
    return {'case': 'step3b_sort_contract_fallback_on_duplicate_key', 'normalize_sort_profile': profile, 'ok': bool(ok)}


def run_step3b_sort_contract_fallback_on_unsorted_unsampled_inversion_case(root: Path) -> dict[str, Any]:
    result = run_step3b_sort_contract_case(
        root,
        'PERF_SMOKE_SORT_CONTRACT_UNSAMPLED_INVERSION',
        trust=True,
        unsampled_inversion=True,
    )
    profile = (((result.get('metadata') or {}).get('performance_profile') or {}).get('normalize_sort_profile') or {})
    ok = (
        result.get('rc') == 0
        and profile.get('sort_contract_trusted') is False
        and profile.get('full_sort_skipped') is False
        and profile.get('fallback_reason') in {'global_sortedness_failed', 'per_group_sortedness_failed'}
    )
    return {
        'case': 'step3b_sort_contract_fallback_on_unsorted_unsampled_inversion',
        'normalize_sort_profile': profile,
        'ok': bool(ok),
    }


def run_step3b_sort_contract_output_parity_with_full_sort_case(root: Path) -> dict[str, Any]:
    trusted = run_step3b_sort_contract_case(root, 'PERF_SMOKE_SORT_CONTRACT_PARITY_TRUSTED', trust=True)
    reference = run_step3b_sort_contract_case(root, 'PERF_SMOKE_SORT_CONTRACT_PARITY_REFERENCE', trust=False)
    fallback = run_step3b_sort_contract_case(
        root,
        'PERF_SMOKE_SORT_CONTRACT_PARITY_UNSORTED_FALLBACK',
        trust=True,
        unsampled_inversion=True,
    )
    trusted_values = trusted.get('values', pd.DataFrame())
    reference_values = reference.get('values', pd.DataFrame())
    fallback_values = fallback.get('values', pd.DataFrame())
    equal = (
        trusted.get('rc') == 0
        and reference.get('rc') == 0
        and list(trusted_values.columns) == list(reference_values.columns)
        and trusted_values.reset_index(drop=True).equals(reference_values.reset_index(drop=True))
    )
    profile = (((trusted.get('metadata') or {}).get('performance_profile') or {}).get('normalize_sort_profile') or {})
    fallback_profile = (((fallback.get('metadata') or {}).get('performance_profile') or {}).get('normalize_sort_profile') or {})
    fallback_reference = fallback.get('daily', pd.DataFrame())
    fallback_sorted = fallback_values[['ts_code', 'trade_date']].astype(str).reset_index(drop=True).equals(
        fallback_reference[['ts_code', 'trade_date']]
        .assign(trade_date=lambda x: x['trade_date'].astype(str))
        .sort_values(['ts_code', 'trade_date'])
        .reset_index(drop=True)
        .astype(str)
    )
    return {
        'case': 'step3b_sort_contract_output_parity_with_full_sort',
        'trusted_rc': trusted.get('rc'),
        'reference_rc': reference.get('rc'),
        'fallback_rc': fallback.get('rc'),
        'row_count_equal': len(trusted_values) == len(reference_values),
        'output_equal': bool(equal),
        'unsorted_fallback_output_sorted': bool(fallback_sorted),
        'trusted_normalize_sort_profile': profile,
        'fallback_normalize_sort_profile': fallback_profile,
        'ok': bool(
            equal
            and profile.get('full_sort_skipped') is True
            and fallback_profile.get('full_sort_skipped') is False
            and fallback_sorted
        ),
    }


def run_step3b_profile_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP3B'
    impl, local_inputs = create_step3b_fixture(root, report_id)
    module = import_run_step3b(root)
    outputs = module.generate_first_run_factor_values(
        report_id=report_id,
        factor_id='SMOKE',
        implementation_path=impl,
        local_inputs=local_inputs,
        step2_research_context={'smoke': True},
        mode_decision={'implementation_mode': 'direct_code'},
        artifact_identity={},
    )
    meta_path = root / outputs['run_metadata_path']
    metadata = read_json(meta_path)
    profile = metadata.get('performance_profile') or {}
    input_io_profile = profile.get('input_io_profile') or {}
    csv_output_profile = profile.get('csv_output_profile') or {}
    required_phases = {'read_inputs', 'compute_factor', 'normalize_sort', 'write_parquet', 'write_csv', 'total'}
    ok = (
        profile.get('version') == 'factorforge_step3b_performance_profile_v1'
        and profile.get('row_count') == outputs.get('row_count')
        and required_phases.issubset(set((profile.get('phase_seconds') or {}).keys()))
        and isinstance(profile.get('formula_engine_profile'), dict)
        and input_io_profile.get('daily_selected_format') == 'parquet'
        and str(input_io_profile.get('daily_selected_path') or '').endswith('.parquet')
        and csv_output_profile.get('csv_output_policy') == 'full_csv'
        and csv_output_profile.get('full_csv_available') is True
        and (profile.get('output_bytes') or {}).get('parquet', 0) > 0
        and (profile.get('output_bytes') or {}).get('csv', 0) > 0
    )
    return {'case': 'step3b_performance_profile_present', 'report_id': report_id, 'profile': profile, 'input_io_profile': input_io_profile, 'ok': bool(ok)}


def run_step3a_daily_parquet_contract_case(root: Path) -> dict[str, Any]:
    report_id = 'STEP_PERF_IO_CONTRACT'
    module = import_run_step3(root)
    local_inputs = module.build_local_price_volume_snapshots(report_id, {'start': '20160104', 'end': '20160329'})
    parquet_path = root.parent / local_inputs.get('daily_df_parquet', '')
    csv_path = root.parent / local_inputs.get('daily_df_csv', '')
    contract = local_inputs.get('daily_io_contract') or {}
    write_step3_validation_artifacts(root, report_id, local_inputs)
    validate_proc = run_cmd([
        sys.executable,
        'skills/factor-forge-step3/scripts/validate_step3.py',
        '--report-id',
        report_id,
    ], root=root)
    ok = (
        local_inputs.get('preferred_daily_format') == 'parquet'
        and local_inputs.get('audit_daily_format') == 'csv'
        and contract.get('version') == 'factorforge_step3a_daily_io_contract_v1'
        and contract.get('csv_output_policy') == 'full_csv'
        and contract.get('full_csv_available') is True
        and parquet_path.exists()
        and csv_path.exists()
        and validate_proc.returncode == 0
    )
    return {
        'case': 'step3a_daily_full_csv_policy_contract',
        'report_id': report_id,
        'local_input_paths': local_inputs,
        'parquet_exists': parquet_path.exists(),
        'csv_exists': csv_path.exists(),
        'validate_rc': validate_proc.returncode,
        'validator_stdout_tail': tail(validate_proc.stdout),
        'validator_stderr_tail': tail(validate_proc.stderr),
        'ok': bool(ok),
    }


def run_step3a_daily_sample_csv_policy_case(root: Path) -> dict[str, Any]:
    report_id = 'STEP_PERF_IO_SAMPLE_POLICY'
    module = import_run_step3(root)
    local_inputs = module.build_local_price_volume_snapshots(report_id, {'start': '20160104', 'end': '20160329'}, csv_output_policy='sample_csv')
    parquet_path = root.parent / local_inputs.get('daily_df_parquet', '')
    full_csv_path = root / 'runs' / report_id / 'step3a_local_inputs' / f'daily_input__{report_id}.csv'
    sample_csv_path = root.parent / local_inputs.get('daily_df_csv_sample', '')
    contract = local_inputs.get('daily_io_contract') or {}
    write_step3_validation_artifacts(root, report_id, local_inputs)
    validate_proc = run_cmd([
        sys.executable,
        'skills/factor-forge-step3/scripts/validate_step3.py',
        '--report-id',
        report_id,
    ], root=root)
    parquet_cols = list(pd.read_parquet(parquet_path).head(0).columns) if parquet_path.exists() else []
    sample_cols = list(pd.read_csv(sample_csv_path, nrows=0).columns) if sample_csv_path.exists() else []
    ok = (
        parquet_path.exists()
        and not full_csv_path.exists()
        and sample_csv_path.exists()
        and local_inputs.get('audit_daily_format') == 'csv_sample'
        and contract.get('csv_output_policy') == 'sample_csv'
        and contract.get('full_csv_available') is False
        and validate_proc.returncode == 0
        and parquet_cols == sample_cols
    )
    return {
        'case': 'step3a_daily_sample_csv_policy_contract',
        'report_id': report_id,
        'parquet_exists': parquet_path.exists(),
        'full_csv_exists': full_csv_path.exists(),
        'sample_csv_exists': sample_csv_path.exists(),
        'contract': contract,
        'validate_rc': validate_proc.returncode,
        'parquet_cols': parquet_cols,
        'sample_cols': sample_cols,
        'ok': bool(ok),
    }


def run_step3a_daily_no_csv_policy_case(root: Path) -> dict[str, Any]:
    report_id = 'STEP_PERF_IO_NO_CSV_POLICY'
    module = import_run_step3(root)
    local_inputs = module.build_local_price_volume_snapshots(report_id, {'start': '20160104', 'end': '20160329'}, csv_output_policy='no_csv')
    parquet_path = root.parent / local_inputs.get('daily_df_parquet', '')
    full_csv_path = root / 'runs' / report_id / 'step3a_local_inputs' / f'daily_input__{report_id}.csv'
    sample_csv_path = root / 'runs' / report_id / 'step3a_local_inputs' / f'daily_input_sample__{report_id}.csv'
    contract = local_inputs.get('daily_io_contract') or {}
    write_step3_validation_artifacts(root, report_id, local_inputs)
    validate_proc = run_cmd([
        sys.executable,
        'skills/factor-forge-step3/scripts/validate_step3.py',
        '--report-id',
        report_id,
    ], root=root)
    ok = (
        parquet_path.exists()
        and not full_csv_path.exists()
        and not sample_csv_path.exists()
        and local_inputs.get('audit_daily_format') == 'none'
        and contract.get('csv_output_policy') == 'no_csv'
        and int(contract.get('csv_rows_written') if contract.get('csv_rows_written') is not None else -1) == 0
        and validate_proc.returncode == 0
    )
    return {
        'case': 'step3a_daily_no_csv_policy_contract',
        'report_id': report_id,
        'parquet_exists': parquet_path.exists(),
        'full_csv_exists': full_csv_path.exists(),
        'sample_csv_exists': sample_csv_path.exists(),
        'contract': contract,
        'validate_rc': validate_proc.returncode,
        'ok': bool(ok),
    }


def run_step3_daily_parquet_csv_schema_parity_case(root: Path) -> dict[str, Any]:
    report_id = 'STEP_PERF_IO_CONTRACT'
    parquet_path = root / 'runs' / report_id / 'step3a_local_inputs' / f'daily_input__{report_id}.parquet'
    csv_path = root / 'runs' / report_id / 'step3a_local_inputs' / f'daily_input__{report_id}.csv'
    if not parquet_path.exists() or not csv_path.exists():
        return {'case': 'step3_daily_parquet_csv_schema_parity', 'parquet_exists': parquet_path.exists(), 'csv_exists': csv_path.exists(), 'ok': False}
    parquet_df = pd.read_parquet(parquet_path)
    csv_df = pd.read_csv(csv_path)
    key_cols = {'ts_code', 'trade_date'}
    numeric_cols = [col for col in ['open', 'high', 'low', 'close', 'pct_chg', 'vol', 'amount'] if col in parquet_df.columns and col in csv_df.columns]
    key_equal = parquet_df[sorted(key_cols)].astype(str).equals(csv_df[sorted(key_cols)].astype(str))
    numeric_equal = all(np.allclose(pd.to_numeric(parquet_df[col], errors='coerce'), pd.to_numeric(csv_df[col], errors='coerce'), equal_nan=True) for col in numeric_cols)
    ok = (
        len(parquet_df) == len(csv_df)
        and set(parquet_df.columns) == set(csv_df.columns)
        and key_equal
        and numeric_equal
    )
    return {
        'case': 'step3_daily_parquet_csv_schema_parity',
        'report_id': report_id,
        'row_count_parquet': int(len(parquet_df)),
        'row_count_csv': int(len(csv_df)),
        'key_equal': bool(key_equal),
        'numeric_cols_checked': numeric_cols,
        'numeric_equal': bool(numeric_equal),
        'ok': bool(ok),
    }


def write_step3_validation_artifacts(root: Path, report_id: str, local_inputs: dict[str, Any]) -> None:
    objects = root / 'objects'
    write_json(objects / 'data_prep_master' / f'data_prep_master__{report_id}.json', {
        'report_id': report_id,
        'factor_id': 'SMOKE',
        'feasibility': 'ready',
        'sample_window': {'start': '20200101', 'end': '20200103'},
        'data_sources': [{'name': 'synthetic_tmp_fixture'}],
        'field_mapping': {'ts_code': 'ts_code', 'trade_date': 'trade_date', 'close': 'close'},
        'proxy_rules': [],
        'coverage_checks': [{'name': 'fixture', 'status': 'pass'}],
        'implementation_notes': ['tmp fixture'],
        'blocked_items': [],
        'local_input_paths': local_inputs,
    })
    write_json(objects / 'data_prep_master' / f'qlib_adapter_config__{report_id}.json', {
        'report_id': report_id,
        'factor_id': 'SMOKE',
        'logical_fields': {'close': 'close'},
        'qlib_field_map': {'$close': 'close'},
        'instrument_field': 'ts_code',
        'date_field': 'trade_date',
    })
    write_json(objects / 'implementation_plan_master' / f'implementation_plan_master__{report_id}.json', {
        'report_id': report_id,
        'factor_id': 'SMOKE',
        'implementation_mode': 'direct_code',
        'calculation_steps': ['read daily snapshot', 'compute smoke factor'],
        'step4_contract': {'execution_mode': 'direct_code'},
    })
    write_json(objects / 'handoff' / f'handoff_to_step4__{report_id}.json', {
        'report_id': report_id,
        'factor_id': 'SMOKE',
        'step3a_ready': True,
        'step3b_ready': True,
        'execution_mode': 'direct_code',
        'local_input_paths': local_inputs,
    })


def run_step3_daily_large_schema_mismatch_block_case(root: Path) -> dict[str, Any]:
    report_id = 'STEP_PERF_IO_SCHEMA_MISMATCH'
    run_dir = root / 'runs' / report_id / 'step3a_local_inputs'
    run_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = run_dir / f'daily_input__{report_id}.parquet'
    csv_path = run_dir / f'daily_input__{report_id}.csv'
    frame = pd.DataFrame([
        {'ts_code': 'S001', 'trade_date': '20200101', 'close': 10.0, 'pct_chg': 0.1, 'amount': 1000.0},
        {'ts_code': 'S002', 'trade_date': '20200101', 'close': 11.0, 'pct_chg': 0.2, 'amount': 1200.0},
    ])
    frame.to_parquet(parquet_path, index=False)
    with csv_path.open('wb') as handle:
        handle.write(b'ts_code,trade_date,close,pct_chg\n')
        handle.write(b'S001,20200101,10.0,0.1\n')
        handle.truncate(110_000_000)
    local_inputs = {
        'input_mode': 'daily_only',
        'daily_df_parquet': str(parquet_path.relative_to(root.parent)),
        'daily_df_csv': str(csv_path.relative_to(root.parent)),
        'preferred_daily_format': 'parquet',
        'audit_daily_format': 'csv',
        'daily_io_contract': {
            'version': 'factorforge_step3a_daily_io_contract_v1',
            'performance_path': 'parquet',
            'audit_path': 'csv',
            'csv_output_policy': 'full_csv',
            'csv_rows_written': 1,
            'parquet_rows_written': int(len(frame)),
            'csv_sample_strategy': 'full',
            'full_csv_available': True,
            'schema_parity_required': True,
            'value_parity_required': True,
            'csv_required_for_audit': True,
            'parquet_required_for_performance': True,
        },
    }
    write_step3_validation_artifacts(root, report_id, local_inputs)
    proc = run_cmd([
        sys.executable,
        'skills/factor-forge-step3/scripts/validate_step3.py',
        '--report-id',
        report_id,
    ], root=root)
    output = proc.stdout + proc.stderr
    token_present = 'STEP3_DAILY_PARQUET_CSV_SCHEMA_MISMATCH' in output
    return {
        'case': 'step3_daily_large_schema_mismatch_block',
        'report_id': report_id,
        'rc': proc.returncode,
        'token_present': token_present,
        'csv_size': csv_path.stat().st_size,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': bool(proc.returncode == 1 and token_present),
    }


def run_step3a_daily_sample_schema_mismatch_block_case(root: Path) -> dict[str, Any]:
    report_id = 'STEP_PERF_IO_SAMPLE_SCHEMA_MISMATCH'
    module = import_run_step3(root)
    local_inputs = module.build_local_price_volume_snapshots(report_id, {'start': '20160104', 'end': '20160329'}, csv_output_policy='sample_csv')
    sample_csv_path = root.parent / local_inputs.get('daily_df_csv_sample', '')
    if sample_csv_path.exists():
        lines = sample_csv_path.read_text(encoding='utf-8').splitlines()
        sample_csv_path.write_text('ts_code,trade_date,open,high,low,close\n' + '\n'.join(lines[1:]) + '\n', encoding='utf-8')
    write_step3_validation_artifacts(root, report_id, local_inputs)
    proc = run_cmd([
        sys.executable,
        'skills/factor-forge-step3/scripts/validate_step3.py',
        '--report-id',
        report_id,
    ], root=root)
    output = proc.stdout + proc.stderr
    token_present = 'STEP3_DAILY_PARQUET_CSV_SCHEMA_MISMATCH' in output
    return {
        'case': 'step3a_daily_sample_schema_mismatch_block',
        'report_id': report_id,
        'rc': proc.returncode,
        'token_present': token_present,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': bool(proc.returncode == 1 and token_present),
    }


def run_step3b_factor_sample_csv_policy_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP3B_SAMPLE_CSV'
    impl, local_inputs = create_step3b_fixture(root, report_id)
    module = import_run_step3b(root)
    outputs = module.generate_first_run_factor_values(
        report_id=report_id,
        factor_id='SMOKE',
        implementation_path=impl,
        local_inputs=local_inputs,
        step2_research_context={'smoke': True},
        mode_decision={'implementation_mode': 'direct_code'},
        artifact_identity={},
        csv_output_policy='sample_csv',
    )
    metadata = read_json(root / outputs['run_metadata_path'])
    profile = metadata.get('performance_profile') or {}
    csv_output_profile = profile.get('csv_output_profile') or {}
    factor_parquet = root / 'runs' / report_id / f'factor_values__{report_id}.parquet'
    factor_csv = root / 'runs' / report_id / f'factor_values__{report_id}.csv'
    factor_sample = root / 'runs' / report_id / f'factor_values_sample__{report_id}.csv'
    ok = (
        factor_parquet.exists()
        and not factor_csv.exists()
        and factor_sample.exists()
        and csv_output_profile.get('csv_output_policy') == 'sample_csv'
        and csv_output_profile.get('csv_sample_strategy') == 'head_tail'
        and 'write_csv' in (profile.get('phase_seconds') or {})
    )
    return {
        'case': 'step3b_factor_sample_csv_policy_contract',
        'report_id': report_id,
        'csv_output_profile': csv_output_profile,
        'phase_seconds': profile.get('phase_seconds'),
        'factor_parquet_exists': factor_parquet.exists(),
        'factor_csv_exists': factor_csv.exists(),
        'factor_sample_exists': factor_sample.exists(),
        'ok': bool(ok),
    }


def run_step3b_factor_no_csv_policy_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP3B_NO_CSV'
    impl, local_inputs = create_step3b_fixture(root, report_id)
    module = import_run_step3b(root)
    outputs = module.generate_first_run_factor_values(
        report_id=report_id,
        factor_id='SMOKE',
        implementation_path=impl,
        local_inputs=local_inputs,
        step2_research_context={'smoke': True},
        mode_decision={'implementation_mode': 'direct_code'},
        artifact_identity={},
        csv_output_policy='no_csv',
    )
    metadata = read_json(root / outputs['run_metadata_path'])
    profile = metadata.get('performance_profile') or {}
    csv_output_profile = profile.get('csv_output_profile') or {}
    factor_parquet = root / 'runs' / report_id / f'factor_values__{report_id}.parquet'
    factor_csv = root / 'runs' / report_id / f'factor_values__{report_id}.csv'
    factor_sample = root / 'runs' / report_id / f'factor_values_sample__{report_id}.csv'
    ok = (
        factor_parquet.exists()
        and not factor_csv.exists()
        and not factor_sample.exists()
        and csv_output_profile.get('csv_output_policy') == 'no_csv'
        and int(csv_output_profile.get('csv_rows_written') if csv_output_profile.get('csv_rows_written') is not None else -1) == 0
        and 'write_csv' in (profile.get('phase_seconds') or {})
    )
    return {
        'case': 'step3b_factor_no_csv_policy_contract',
        'report_id': report_id,
        'csv_output_profile': csv_output_profile,
        'phase_seconds': profile.get('phase_seconds'),
        'factor_parquet_exists': factor_parquet.exists(),
        'factor_csv_exists': factor_csv.exists(),
        'factor_sample_exists': factor_sample.exists(),
        'ok': bool(ok),
    }


def _read_step3b_csv_profile(root: Path, report_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    meta_path = root / 'runs' / report_id / f'run_metadata__{report_id}.json'
    metadata = read_json(meta_path) if meta_path.exists() else {}
    profile = metadata.get('performance_profile') or {}
    return metadata, profile.get('csv_output_profile') or {}


def run_csv_policy_sample_csv_parquet_formal_evidence_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP3B_SAMPLE_CSV'
    metadata, csv_profile = _read_step3b_csv_profile(root, report_id)
    factor_parquet = root / 'runs' / report_id / f'factor_values__{report_id}.parquet'
    factor_csv = root / 'runs' / report_id / f'factor_values__{report_id}.csv'
    factor_sample = root / 'runs' / report_id / f'factor_values_sample__{report_id}.csv'
    ok = (
        bool(metadata)
        and factor_parquet.exists()
        and not factor_csv.exists()
        and factor_sample.exists()
        and csv_profile.get('version') == 'factorforge_csv_output_profile_v1'
        and csv_profile.get('formal_evidence_format') == 'parquet'
        and csv_profile.get('csv_output_policy') == 'sample_csv'
        and csv_profile.get('factor_parquet_path') == str(factor_parquet)
        and csv_profile.get('factor_csv_path') is None
        and csv_profile.get('factor_sample_csv_path') == str(factor_sample)
        and csv_profile.get('sample_schema_parity') is True
        and csv_profile.get('full_csv_absent_validated') is True
    )
    return {
        'case': 'csv_policy_sample_csv_parquet_formal_evidence',
        'report_id': report_id,
        'csv_output_profile': csv_profile,
        'factor_parquet_exists': factor_parquet.exists(),
        'factor_csv_exists': factor_csv.exists(),
        'factor_sample_exists': factor_sample.exists(),
        'ok': bool(ok),
    }


def run_csv_policy_no_csv_parquet_formal_evidence_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP3B_NO_CSV'
    metadata, csv_profile = _read_step3b_csv_profile(root, report_id)
    factor_parquet = root / 'runs' / report_id / f'factor_values__{report_id}.parquet'
    factor_csv = root / 'runs' / report_id / f'factor_values__{report_id}.csv'
    factor_sample = root / 'runs' / report_id / f'factor_values_sample__{report_id}.csv'
    ok = (
        bool(metadata)
        and factor_parquet.exists()
        and not factor_csv.exists()
        and not factor_sample.exists()
        and csv_profile.get('version') == 'factorforge_csv_output_profile_v1'
        and csv_profile.get('formal_evidence_format') == 'parquet'
        and csv_profile.get('csv_output_policy') == 'no_csv'
        and csv_profile.get('factor_parquet_path') == str(factor_parquet)
        and csv_profile.get('factor_csv_path') is None
        and csv_profile.get('factor_sample_csv_path') is None
        and csv_profile.get('sample_schema_parity') is None
        and csv_profile.get('full_csv_absent_validated') is True
    )
    return {
        'case': 'csv_policy_no_csv_parquet_formal_evidence',
        'report_id': report_id,
        'csv_output_profile': csv_profile,
        'factor_parquet_exists': factor_parquet.exists(),
        'factor_csv_exists': factor_csv.exists(),
        'factor_sample_exists': factor_sample.exists(),
        'ok': bool(ok),
    }


def run_csv_policy_full_csv_legacy_compat_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP3B'
    metadata, csv_profile = _read_step3b_csv_profile(root, report_id)
    factor_parquet = root / 'runs' / report_id / f'factor_values__{report_id}.parquet'
    factor_csv = root / 'runs' / report_id / f'factor_values__{report_id}.csv'
    ok = (
        bool(metadata)
        and factor_parquet.exists()
        and factor_csv.exists()
        and csv_profile.get('version') == 'factorforge_csv_output_profile_v1'
        and csv_profile.get('formal_evidence_format') == 'parquet'
        and csv_profile.get('csv_output_policy') == 'full_csv'
        and csv_profile.get('factor_parquet_path') == str(factor_parquet)
        and csv_profile.get('factor_csv_path') == str(factor_csv)
        and csv_profile.get('full_csv_available') is True
        and csv_profile.get('full_csv_absent_validated') is False
    )
    return {
        'case': 'csv_policy_full_csv_legacy_compat',
        'report_id': report_id,
        'csv_output_profile': csv_profile,
        'factor_parquet_exists': factor_parquet.exists(),
        'factor_csv_exists': factor_csv.exists(),
        'ok': bool(ok),
    }


def run_validate_step3_accepts_no_csv_with_parquet_case(root: Path) -> dict[str, Any]:
    report_id = 'STEP_PERF_IO_NO_CSV_POLICY'
    proc = run_cmd([
        sys.executable,
        'skills/factor-forge-step3/scripts/validate_step3.py',
        '--report-id',
        report_id,
    ], root=root)
    output = proc.stdout + proc.stderr
    return {
        'case': 'validate_step3_accepts_no_csv_with_parquet',
        'report_id': report_id,
        'rc': proc.returncode,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': bool(proc.returncode == 0 and 'RESULT: PASS' in output),
    }


def run_csv_policy_invalid_blocks_case(root: Path) -> dict[str, Any]:
    module = import_run_step3(root)
    try:
        module.resolve_csv_policy('bad_policy')
    except SystemExit as exc:
        token_present = 'BLOCK_FACTORFORGE_INVALID_CSV_OUTPUT_POLICY' in str(exc)
        return {
            'case': 'csv_policy_invalid_blocks',
            'rc': 1,
            'token_present': token_present,
            'message': str(exc),
            'ok': bool(token_present),
        }
    return {'case': 'csv_policy_invalid_blocks', 'rc': 0, 'token_present': False, 'ok': False}


def run_csv_policy_invalid_cli_blocks_case(root: Path) -> dict[str, Any]:
    step3_proc = run_cmd([
        sys.executable,
        'skills/factor-forge-step3/scripts/run_step3.py',
        '--report-id',
        'CSV_POLICY_INVALID_CLI_STEP3',
        '--csv-output-policy',
        'bad_policy',
    ], root=root)
    step3b_proc = run_cmd([
        sys.executable,
        'skills/factor-forge-step3/scripts/run_step3b.py',
        '--report-id',
        'CSV_POLICY_INVALID_CLI_STEP3B',
        '--csv-output-policy',
        'bad_policy',
    ], root=root)
    step3_output = step3_proc.stdout + step3_proc.stderr
    step3b_output = step3b_proc.stdout + step3b_proc.stderr
    step3_token = 'BLOCK_FACTORFORGE_INVALID_CSV_OUTPUT_POLICY' in step3_output
    step3b_token = 'BLOCK_FACTORFORGE_INVALID_CSV_OUTPUT_POLICY' in step3b_output
    ok = step3_proc.returncode != 0 and step3b_proc.returncode != 0 and step3_token and step3b_token
    return {
        'case': 'csv_policy_invalid_cli_blocks',
        'step3_rc': step3_proc.returncode,
        'step3_token_present': step3_token,
        'step3_stdout_tail': tail(step3_proc.stdout),
        'step3_stderr_tail': tail(step3_proc.stderr),
        'step3b_rc': step3b_proc.returncode,
        'step3b_token_present': step3b_token,
        'step3b_stdout_tail': tail(step3b_proc.stdout),
        'step3b_stderr_tail': tail(step3b_proc.stderr),
        'ok': bool(ok),
    }


def run_step3a_daily_no_csv_contract_stale_path_block_case(root: Path) -> dict[str, Any]:
    report_id = 'STEP_PERF_IO_NO_CSV_STALE_PATH'
    module = import_run_step3(root)
    local_inputs = module.build_local_price_volume_snapshots(report_id, {'start': '20160104', 'end': '20160329'}, csv_output_policy='no_csv')
    contract = local_inputs.get('daily_io_contract') or {}
    contract['csv_path'] = f'runs/{report_id}/step3a_local_inputs/stale_full.csv'
    contract['csv_sample_path'] = f'runs/{report_id}/step3a_local_inputs/stale_sample.csv'
    write_step3_validation_artifacts(root, report_id, local_inputs)
    proc = run_cmd([
        sys.executable,
        'skills/factor-forge-step3/scripts/validate_step3.py',
        '--report-id',
        report_id,
    ], root=root)
    output = proc.stdout + proc.stderr
    token_present = 'STEP3_DAILY_NO_CSV_PATH_DECLARED' in output
    return {
        'case': 'step3a_daily_no_csv_contract_stale_path_block',
        'report_id': report_id,
        'rc': proc.returncode,
        'token_present': token_present,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': bool(proc.returncode == 1 and token_present),
    }


def run_price_volume_plugin_uses_volume_case() -> dict[str, Any]:
    report_id = 'PERF_SMOKE_PRICE_VOLUME_PLUGIN'
    plan, _stub, qlib, scaffold = PRICE_VOLUME_PLUGIN.generate(
        report_id,
        prep={'sample_window': {'start': '20200101', 'end': '20200101'}},
        spec={'factor_id': 'PRICE_VOLUME_SMOKE'},
    )
    namespace: dict[str, Any] = {}
    exec(_stub, namespace)
    compute_factor = namespace['compute_factor']
    daily = pd.DataFrame([
        {'ts_code': 'A', 'trade_date': '20200101', 'open': 10.0, 'close': 11.0, 'vol': 100.0},
        {'ts_code': 'B', 'trade_date': '20200101', 'open': 10.0, 'close': 11.0, 'vol': 200.0},
    ])
    out = compute_factor(daily)
    signal_col = str(plan['output_schema']['columns'][-1])
    missing_vol_blocked = False
    try:
        compute_factor(daily.drop(columns=['vol']))
    except KeyError as exc:
        missing_vol_blocked = 'vol' in str(exc)
    values = out.sort_values('ts_code')[signal_col].to_numpy(dtype=float)
    ok = (
        signal_col in out.columns
        and missing_vol_blocked
        and len(values) == 2
        and values[1] > values[0]
        and plan.get('factor_family') == 'price_volume'
        and qlib.get('mode') == 'price_volume_family'
        and scaffold.get('producer') == 'factor_family_plugin'
    )
    return {
        'case': 'price_volume_plugin_uses_volume',
        'signal_col': signal_col,
        'values': values.tolist(),
        'missing_vol_blocked': missing_vol_blocked,
        'ok': bool(ok),
    }


def run_step3b_prefers_daily_parquet_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP3B_PARQUET_PREFERRED'
    impl, local_inputs = create_step3b_fixture(root, report_id)
    module = import_run_step3b(root)
    outputs = module.generate_first_run_factor_values(
        report_id=report_id,
        factor_id='SMOKE',
        implementation_path=impl,
        local_inputs=local_inputs,
        step2_research_context={'smoke': True},
        mode_decision={'implementation_mode': 'direct_code'},
        artifact_identity={},
    )
    metadata = read_json(root / outputs['run_metadata_path'])
    input_io_profile = (metadata.get('performance_profile') or {}).get('input_io_profile') or {}
    ok = (
        input_io_profile.get('daily_selected_format') == 'parquet'
        and str(input_io_profile.get('daily_selected_path') or '').endswith('.parquet')
    )
    return {'case': 'step3b_prefers_daily_parquet_when_available', 'report_id': report_id, 'input_io_profile': input_io_profile, 'ok': bool(ok)}


def build_formula_fixture_frame(unsorted: bool = False) -> pd.DataFrame:
    rows = []
    for code_idx, code in enumerate(['S001', 'S002', 'S003', 'S004']):
        for day_idx, dt in enumerate(pd.bdate_range('2020-01-01', periods=34), start=1):
            trade_date = dt.strftime('%Y%m%d')
            close = 10.0 + code_idx * 1.5 + (day_idx % 7) * 0.2
            if code == 'S003' and day_idx in {8, 9, 10}:
                close = np.nan
            if code == 'S002' and day_idx in {12, 13, 14}:
                close = 15.0
            rows.append({
                'ts_code': code,
                'trade_date': trade_date,
                'open': close - 0.1 if not np.isnan(close) else np.nan,
                'high': close + 0.4 if not np.isnan(close) else np.nan,
                'low': close - 0.5 if not np.isnan(close) else np.nan,
                'close': close,
                'volume': float(1000 + code_idx * 100 + (day_idx % 5) * 20),
                'vol': float(1000 + code_idx * 100 + (day_idx % 5) * 20),
                'amount': float((close if not np.isnan(close) else 10.0) * (1000 + code_idx * 100 + day_idx)),
                'pct_chg': float((code_idx - 1.5) * 0.01 + day_idx * 0.0001),
            })
    frame = pd.DataFrame(rows)
    if unsorted:
        frame = frame.iloc[[*range(3, len(frame), 4), *range(1, len(frame), 4), *range(0, len(frame), 4), *range(2, len(frame), 4)]].reset_index(drop=True)
    return frame


def assert_series_equal_with_nan(reference: pd.Series, optimized: pd.Series) -> tuple[bool, float]:
    ref = pd.to_numeric(reference, errors='coerce').reset_index(drop=True)
    opt = pd.to_numeric(optimized, errors='coerce').reset_index(drop=True)
    ref_mask = ref.isna()
    opt_mask = opt.isna()
    if not ref_mask.equals(opt_mask):
        return False, float('inf')
    diffs = (ref[~ref_mask] - opt[~opt_mask]).abs()
    max_abs = float(diffs.max()) if len(diffs) else 0.0
    return bool(np.isfinite(max_abs) and max_abs <= 1e-12), max_abs


def run_formula_evaluator_parity_case() -> dict[str, Any]:
    frame = build_formula_fixture_frame(unsorted=False)
    formulas = [
        'rank(ts_rank(close, 10))',
        'delta(delta(close, 1), 1)',
        'ts_rank(volume / mean(volume, 20), 5)',
        'rank(correlation(rank(high), rank(volume), 3))',
        'rank(ts_rank(close, 5)) + rank(ts_rank(close, 5))',
    ]
    results = []
    ok = True
    for formula in formulas:
        formula_ir = parse_formula(formula, available_columns=list(frame.columns), raise_on_error=True)
        ref = evaluate_formula_ir(formula_ir, frame, engine='reference')
        opt = evaluate_formula_ir(formula_ir, frame, engine='optimized')
        equal, max_abs_diff = assert_series_equal_with_nan(ref, opt)
        results.append({'formula': formula, 'equal': equal, 'max_abs_diff': max_abs_diff})
        ok = ok and equal
    return {'case': 'formula_evaluator_reference_optimized_parity', 'fixtures': results, 'ok': bool(ok)}


def run_formula_evaluator_cache_case() -> dict[str, Any]:
    frame = build_formula_fixture_frame()
    formula = 'rank(ts_rank(close, 5)) + rank(ts_rank(close, 5))'
    formula_ir = parse_formula(formula, available_columns=list(frame.columns), raise_on_error=True)
    _values, profile = evaluate_formula_ir_optimized(formula_ir, frame, return_profile=True)
    ok = (profile.get('cache_hits') or 0) > 0 and (profile.get('cache_misses') or 0) > 0
    return {'case': 'formula_evaluator_cache_hits_present', 'profile': profile, 'ok': bool(ok)}


def run_formula_evaluator_unsorted_case() -> dict[str, Any]:
    sorted_frame = build_formula_fixture_frame(unsorted=False)
    unsorted_frame = build_formula_fixture_frame(unsorted=True)
    formula = 'rank(correlation(rank(high), rank(volume), 3))'
    formula_ir = parse_formula(formula, available_columns=list(sorted_frame.columns), raise_on_error=True)
    ref = evaluate_formula_ir(formula_ir, unsorted_frame, engine='reference')
    opt = evaluate_formula_ir(formula_ir, unsorted_frame, engine='optimized')
    equal, max_abs_diff = assert_series_equal_with_nan(ref, opt)
    return {'case': 'formula_evaluator_unsorted_input_parity', 'max_abs_diff': max_abs_diff, 'ok': bool(equal)}


def _operator_profile_from_formula(formula: str, frame: pd.DataFrame) -> dict[str, Any]:
    formula_ir = parse_formula(formula, available_columns=list(frame.columns), raise_on_error=True)
    _out, profile = evaluate_formula_frame(
        formula_ir,
        frame,
        engine='optimized',
        return_profile=True,
        operator_profile_enabled=True,
    )
    return profile.get('operator_profile') or {}


def run_operator_profile_basic_present_case() -> dict[str, Any]:
    frame = build_formula_fixture_frame()
    op_profile = _operator_profile_from_formula('rank(delta(close, 1) * (volume / close))', frame)
    by_operator = op_profile.get('by_operator') or {}
    ok = bool(
        op_profile.get('version') == 'factorforge_operator_profile_v1'
        and op_profile.get('enabled') is True
        and int(op_profile.get('event_count') or 0) > 0
        and {'rank', 'delta', 'mul', 'div'}.issubset(set(by_operator))
    )
    return {'case': 'operator_profile_basic_present', 'operator_profile': op_profile, 'ok': ok}


def run_operator_profile_alpha017_like_breakdown_case() -> dict[str, Any]:
    frame = build_polars_alpha017_like_frame()
    formula = '- rank(ts_rank(close, 10)) * rank(delta(delta(close, 1), 1)) * rank(ts_rank(volume / close, 5))'
    op_profile = _operator_profile_from_formula(formula, frame)
    by_operator = op_profile.get('by_operator') or {}
    required = {'ts_rank', 'rank', 'delta', 'mul', 'div', 'neg'}
    ok = bool(
        op_profile.get('enabled') is True
        and required.issubset(set(by_operator))
        and bool(op_profile.get('top_events'))
    )
    return {
        'case': 'operator_profile_alpha017_like_breakdown',
        'required_operators': sorted(required),
        'present_operators': sorted(by_operator),
        'top_events': op_profile.get('top_events'),
        'ok': ok,
    }


def run_operator_profile_cache_hit_recorded_case() -> dict[str, Any]:
    frame = build_formula_fixture_frame()
    op_profile = _operator_profile_from_formula('rank(ts_rank(close, 5)) + rank(ts_rank(close, 5))', frame)
    by_operator = op_profile.get('by_operator') or {}
    cache_hit_events = [event for event in (op_profile.get('top_events') or []) if event.get('cache_hit')]
    any_cache_hit = any((bucket.get('cache_hit_count') or 0) > 0 for bucket in by_operator.values())
    ok = bool(
        op_profile.get('enabled') is True
        and any_cache_hit
        and float(sum((bucket.get('total_seconds') or 0.0) for bucket in by_operator.values())) >= 0.0
    )
    return {
        'case': 'operator_profile_cache_hit_recorded',
        'cache_hit_events_in_top_events': cache_hit_events,
        'by_operator': by_operator,
        'ok': ok,
    }


def build_polars_alpha017_like_frame(unsorted: bool = True) -> pd.DataFrame:
    rows = []
    dates = pd.bdate_range('2020-01-01', periods=135)
    for code_idx in range(42):
        code = f'P{code_idx:04d}'
        for day_idx, dt in enumerate(dates):
            close = 10.0 + code_idx * 0.15 + (day_idx % 17) * 0.03
            if code_idx % 9 == 0 and day_idx in {12, 13, 14}:
                close = np.nan
            if code_idx % 7 == 0 and day_idx in {30, 31, 32}:
                close = 18.0
            volume = float(1000 + code_idx * 13 + (day_idx % 11) * 7)
            adv20 = float(1100 + code_idx * 11 + (day_idx % 5) * 6)
            if day_idx in {20, 21} and code_idx % 10 == 0:
                adv20 = np.nan
            rows.append({
                'ts_code': code,
                'trade_date': dt.strftime('%Y%m%d'),
                'close': close,
                'volume': volume,
                'adv20': adv20,
                'pct_chg': float((code_idx % 5 - 2) * 0.001 + day_idx * 0.00001),
            })
    frame = pd.DataFrame(rows)
    if unsorted:
        frame = frame.iloc[[*range(5, len(frame), 7), *range(2, len(frame), 7), *range(0, len(frame), 7), *range(1, len(frame), 7), *range(3, len(frame), 7), *range(4, len(frame), 7), *range(6, len(frame), 7)]].reset_index(drop=True)
    return frame


def run_polars_dependency_probe_case() -> dict[str, Any]:
    available = polars_dependency_available()
    return {
        'case': 'polars_dependency_probe',
        'polars_installed': bool(available),
        'ok': True,
    }


def _run_polars_formula_parity_case(case: str, frame: pd.DataFrame, formula: str) -> dict[str, Any]:
    if not polars_dependency_available():
        return {
            'case': case,
            'polars_installed': False,
            'skipped_reason': 'polars_dependency_missing',
            'ok': True,
        }
    formula_ir = parse_formula(formula, available_columns=list(frame.columns), raise_on_error=True)
    reference = evaluate_formula_frame(formula_ir, frame, engine='reference')
    experimental, profile = evaluate_formula_frame(formula_ir, frame, engine='polars_experimental', return_profile=True)
    parity = assert_polars_result_parity(reference, experimental, tolerance=1e-12)
    ok = bool(
        profile.get('engine') == 'polars_experimental'
        and profile.get('polars_used') is True
        and profile.get('polars_fallback_used') is False
        and parity.get('row_count_equal') is True
        and parity.get('key_order_equal') is True
        and parity.get('nan_mask_equal') is True
        and float(parity.get('max_abs_diff') or 0.0) <= 1e-12
        and ((parity.get('rank_corr') is None) or float(parity.get('rank_corr')) >= 0.999999)
    )
    return {
        'case': case,
        'polars_installed': True,
        'formula': formula,
        'profile': profile,
        **parity,
        'ok': ok,
    }


def run_polars_rank_nan_parity_case() -> dict[str, Any]:
    frame = pd.DataFrame({
        'ts_code': ['A', 'B', 'C', 'D', 'E', 'A', 'B', 'C', 'D', 'E'],
        'trade_date': ['20200101'] * 5 + ['20200102'] * 5,
        'close': [1.0, 2.0, 2.0, np.nan, 4.0, np.nan, 3.0, 3.0, 5.0, 1.0],
        'volume': [10.0, 20.0, 21.0, 22.0, 23.0, 11.0, 12.0, 13.0, 14.0, 15.0],
        'pct_chg': [0.0] * 10,
    })
    return _run_polars_formula_parity_case('polars_rank_nan_parity', frame, 'rank(close)')


def run_polars_delta_nan_parity_case() -> dict[str, Any]:
    rows = []
    for code, values in {'A': [1.0, 2.0, np.nan, 5.0, 8.0], 'B': [np.nan, 3.0, 4.0, np.nan, 9.0]}.items():
        for idx, value in enumerate(values):
            rows.append({
                'ts_code': code,
                'trade_date': f'2020010{idx + 1}',
                'close': value,
                'volume': float(100 + idx),
                'pct_chg': 0.0,
            })
    frame = pd.DataFrame(rows).iloc[[2, 0, 7, 4, 1, 5, 3, 9, 6, 8]].reset_index(drop=True)
    return _run_polars_formula_parity_case('polars_delta_nan_parity', frame, 'delta(close, 1)')


def run_polars_arithmetic_nan_parity_case() -> dict[str, Any]:
    rows = []
    dates = pd.bdate_range('2020-01-01', periods=8)
    for code_idx in range(8):
        for day_idx, dt in enumerate(dates):
            close = float(10 + code_idx + day_idx * 0.2)
            if (code_idx, day_idx) in {(1, 2), (3, 4), (5, 0)}:
                close = np.nan
            volume = float(1000 + code_idx * 10 + day_idx)
            rows.append({
                'ts_code': f'P{code_idx:03d}',
                'trade_date': dt.strftime('%Y%m%d'),
                'close': close,
                'volume': volume,
                'pct_chg': 0.0,
            })
    frame = pd.DataFrame(rows).iloc[[*range(3, len(rows), 4), *range(1, len(rows), 4), *range(0, len(rows), 4), *range(2, len(rows), 4)]].reset_index(drop=True)
    return _run_polars_formula_parity_case('polars_arithmetic_nan_parity', frame, 'rank(delta(close, 1) * (volume / close))')


def run_polars_alpha017_subset_parity_case() -> dict[str, Any]:
    frame = build_polars_alpha017_like_frame()
    formula = 'rank(delta(close, 1) * (volume / close))'
    formula_ir = parse_formula(formula, available_columns=list(frame.columns), raise_on_error=True)
    if not polars_dependency_available():
        return {
            'case': 'polars_alpha017_subset_parity',
            'polars_installed': False,
            'skipped_reason': 'polars_dependency_missing',
            'ok': True,
        }
    reference = evaluate_formula_frame(formula_ir, frame, engine='reference')
    experimental, profile = evaluate_formula_frame(formula_ir, frame, engine='polars_experimental', return_profile=True)
    parity = assert_polars_result_parity(reference, experimental, tolerance=1e-12)
    ok = bool(
        profile.get('engine') == 'polars_experimental'
        and profile.get('polars_used') is True
        and profile.get('polars_fallback_used') is False
        and parity.get('row_count_equal') is True
        and parity.get('key_order_equal') is True
        and parity.get('nan_mask_equal') is True
        and float(parity.get('max_abs_diff') or 0.0) <= 1e-12
        and ((parity.get('rank_corr') is None) or float(parity.get('rank_corr')) >= 0.999999)
        and int(parity.get('parity_sample_rows') or 0) >= 5000
    )
    return {
        'case': 'polars_alpha017_subset_parity',
        'polars_installed': True,
        'profile': profile,
        **parity,
        'ok': ok,
    }


def run_polars_unsupported_operator_fallback_or_block_case() -> dict[str, Any]:
    frame = build_polars_alpha017_like_frame()
    formula = 'rank(ts_rank(close, 5))'
    formula_ir = parse_formula(formula, available_columns=list(frame.columns), raise_on_error=True)
    if not polars_dependency_available():
        return {
            'case': 'polars_unsupported_operator_fallback_or_block',
            'polars_installed': False,
            'skipped_reason': 'polars_dependency_missing',
            'ok': True,
        }
    _result, profile = evaluate_formula_frame(formula_ir, frame, engine='polars_experimental', return_profile=True)
    ok = bool(
        profile.get('polars_fallback_used') is True
        and profile.get('polars_used') is False
        and profile.get('polars_fallback_reason') == 'unsupported_operator:ts_rank'
        and profile.get('parity_checked') is True
    )
    return {
        'case': 'polars_unsupported_operator_fallback_or_block',
        'profile': profile,
        'ok': ok,
    }


def run_polars_parity_failure_blocks_case() -> dict[str, Any]:
    reference = pd.DataFrame({
        'ts_code': ['A', 'A', 'B', 'B'],
        'trade_date': ['20200101', '20200102', '20200101', '20200102'],
        'factor_value': [0.1, 0.2, 0.3, 0.4],
    })
    mutated = reference.copy()
    mutated.loc[mutated.index[-1], 'factor_value'] = 99.0
    try:
        assert_polars_result_parity(reference, mutated, tolerance=1e-12)
        token_present = False
    except AssertionError as exc:
        token_present = 'BLOCK_POLARS_EXPERIMENTAL_PARITY_FAILED' in str(exc)
    return {
        'case': 'polars_parity_failure_blocks',
        'token_present': bool(token_present),
        'ok': bool(token_present),
    }


def run_polars_parity_failure_diagnostics_present_case() -> dict[str, Any]:
    reference = pd.DataFrame({
        'ts_code': ['A', 'A', 'B', 'B'],
        'trade_date': ['20200101', '20200102', '20200101', '20200102'],
        'factor_value': [0.1, np.nan, 0.3, 0.4],
    })
    mutated = reference.copy()
    mutated.loc[mutated.index[1], 'factor_value'] = 0.2
    try:
        assert_polars_result_parity(reference, mutated, tolerance=1e-12)
        message = ''
    except AssertionError as exc:
        message = str(exc)
    required = {
        'nan_mask_mismatch_count',
        'reference_nan_count',
        'candidate_nan_count',
        'mismatch_samples',
    }
    ok = bool('BLOCK_POLARS_EXPERIMENTAL_PARITY_FAILED' in message and all(token in message for token in required))
    return {
        'case': 'polars_parity_failure_diagnostics_present',
        'message_tail': tail(message, 1200),
        'ok': ok,
    }


def _rank_corr_for_series(reference: pd.Series, optimized: pd.Series) -> float | None:
    ref = pd.to_numeric(reference, errors='coerce').reset_index(drop=True)
    opt = pd.to_numeric(optimized, errors='coerce').reset_index(drop=True)
    valid = ref.notna() & opt.notna()
    if int(valid.sum()) < 2:
        return None
    corr = ref[valid].rank(method='average').corr(opt[valid].rank(method='average'), method='pearson')
    return float(corr) if pd.notna(corr) else None


def build_ts_rank_large_frame() -> pd.DataFrame:
    rng = np.random.default_rng(17)
    rows = []
    dates = pd.bdate_range('2020-01-01', periods=220)
    for code_idx in range(60):
        code = f'S{code_idx:04d}'
        base = rng.normal(loc=0.0, scale=1.0, size=len(dates)).cumsum()
        for day_idx, dt in enumerate(dates):
            value = float(base[day_idx] + (day_idx % 11) * 0.01)
            if day_idx in {5, 6, 7} and code_idx % 9 == 0:
                value = 3.0
            if day_idx in {17, 18} and code_idx % 13 == 0:
                value = np.nan
            rows.append({'ts_code': code, 'trade_date': dt.strftime('%Y%m%d'), 'x': value})
    frame = pd.DataFrame(rows)
    frame = frame.iloc[[*range(2, len(frame), 3), *range(0, len(frame), 3), *range(1, len(frame), 3)]].reset_index(drop=True)
    return frame.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)


def run_ts_rank_default_disabled_large_case() -> dict[str, Any]:
    frame = build_ts_rank_large_frame()
    series = frame['x']
    window = 20
    with temporary_env('FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_FAST', None):
        start = time.perf_counter()
        reference = ts_rank_reference(series, window, frame)
        reference_time = time.perf_counter() - start
        stats: dict[str, Any] = {}
        start = time.perf_counter()
        optimized = ts_rank(series, window, frame, stats=stats)
        optimized_time = time.perf_counter() - start
    equal, max_abs_diff = assert_series_equal_with_nan(reference, optimized)
    speedup_ratio = float(reference_time / optimized_time) if optimized_time > 0 else None
    rank_corr = _rank_corr_for_series(reference, optimized)
    corr_ok = rank_corr is None or abs(float(rank_corr) - 1.0) <= 1e-12
    ok = bool(
        equal
        and corr_ok
        and stats.get('ts_rank_engine') == 'pandas_reference'
        and stats.get('ts_rank_fast_path_count') == 0
        and stats.get('ts_rank_fast_path_enabled') is False
        and stats.get('ts_rank_fallback_count', 0) >= 1
        and 'experimental_fast_path_disabled' in (stats.get('ts_rank_fallback_reasons') or [])
    )
    return {
        'case': 'ts_rank_default_path_disables_numpy_sliding_window',
        'row_count': int(len(frame)),
        'window': window,
        'reference_time': reference_time,
        'optimized_time': optimized_time,
        'speedup_ratio': speedup_ratio,
        'max_abs_diff': max_abs_diff,
        'rank_corr': rank_corr,
        'stats': stats,
        'ok': ok,
    }


def run_ts_rank_experimental_fast_parity_case() -> dict[str, Any]:
    frame = build_ts_rank_large_frame()
    series = frame['x']
    window = 20
    reference = ts_rank_reference(series, window, frame)
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_FAST': None,
        'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': '1',
        'FACTORFORGE_TS_RANK_ENGINE': 'numpy_sliding_window_experimental',
    }):
        stats: dict[str, Any] = {}
        start = time.perf_counter()
        optimized = ts_rank(series, window, frame, stats=stats)
        optimized_time = time.perf_counter() - start
    equal, max_abs_diff = assert_series_equal_with_nan(reference, optimized)
    rank_corr = _rank_corr_for_series(reference, optimized)
    corr_ok = rank_corr is None or abs(float(rank_corr) - 1.0) <= 1e-12
    ok = bool(
        equal
        and corr_ok
        and stats.get('ts_rank_engine') == 'numpy_sliding_window_experimental'
        and stats.get('ts_rank_fast_path_count') == 1
        and stats.get('ts_rank_fast_path_enabled') is True
    )
    return {
        'case': 'ts_rank_experimental_numpy_sliding_window_parity',
        'row_count': int(len(frame)),
        'window': window,
        'optimized_time': optimized_time,
        'max_abs_diff': max_abs_diff,
        'rank_corr': rank_corr,
        'stats': stats,
        'ok': ok,
    }


def run_ts_rank_candidate_small_parity_case() -> dict[str, Any]:
    raw_frame = build_operator_parity_frame().rename(columns={'x': 'value'})
    frame = prepare_ts_rank_frame(raw_frame)
    window = 5
    candidates = available_candidates()
    reference = candidates['pandas_reference'](frame, 'value', window).values
    results = []
    ok = True
    for name, func in candidates.items():
        candidate = func(frame, 'value', window)
        if candidate.status == 'SKIP':
            results.append({'candidate': name, 'status': 'SKIP', 'skip_reason': candidate.skip_reason, 'parity_pass': False})
            continue
        parity = {'parity_pass': True, 'max_abs_diff': 0.0, 'nan_mask_equal': True, 'key_order_equal': True}
        if name != 'pandas_reference':
            parity = compare_candidate_to_reference(frame, reference, candidate.values)
            ok = ok and bool(parity.get('parity_pass'))
        results.append({'candidate': name, 'status': candidate.status, **parity})
    return {'case': 'ts_rank_candidate_small_parity', 'results': results, 'ok': bool(ok)}


def run_ts_rank_candidate_medium_benchmark_case(root: Path) -> dict[str, Any]:
    bench_root = root / 'ts_rank_candidate_medium_benchmark'
    proc = run_cmd([
        sys.executable,
        'scripts/run_ts_rank_candidate_benchmark.py',
        '--fresh',
        '--root',
        str(bench_root),
        '--windows',
        '5',
    ])
    summary_path = bench_root / 'ts_rank_candidate_benchmark_summary.json'
    summary = read_json(summary_path) if summary_path.exists() else {}
    medium_cases = [case for case in summary.get('cases', []) if str(case.get('case', '')).startswith('medium_panel')]
    reference_pass = any(
        result.get('candidate') == 'pandas_reference' and result.get('status') == 'PASS'
        for case in medium_cases
        for result in case.get('results', [])
    )
    non_ref_seen = any(
        result.get('candidate') != 'pandas_reference' and result.get('status') in {'PASS', 'SKIP', 'FAIL'}
        for case in medium_cases
        for result in case.get('results', [])
    )
    ok = bool(proc.returncode == 0 and summary_path.exists() and summary.get('verdict') == 'ACCEPT' and reference_pass and non_ref_seen)
    return {
        'case': 'ts_rank_candidate_medium_benchmark',
        'rc': proc.returncode,
        'summary_exists': summary_path.exists(),
        'summary_verdict': summary.get('verdict'),
        'reference_pass': reference_pass,
        'non_reference_candidate_recorded': non_ref_seen,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': ok,
    }


def run_ts_rank_candidate_alpha017_sample_readonly_case(root: Path) -> dict[str, Any]:
    alpha_path = REPO_ROOT / 'runs' / 'ALPHA017_CANONICAL_FORMULA_20160101_LOOP_HYP' / 'step3a_local_inputs' / 'daily_input__ALPHA017_CANONICAL_FORMULA_20160101_LOOP_HYP.parquet'
    if not alpha_path.exists():
        return {
            'case': 'ts_rank_candidate_alpha017_sample_readonly',
            'skipped_reason': f'missing_alpha017_daily_parquet:{alpha_path}',
            'ok': True,
        }
    before = snapshot_repo_files()
    bench_root = root / 'ts_rank_candidate_alpha017_sample'
    proc = run_cmd([
        sys.executable,
        'scripts/run_ts_rank_candidate_benchmark.py',
        '--fresh',
        '--root',
        str(bench_root),
        '--include-alpha017-sample',
        '--max-tickers',
        '50',
        '--windows',
        '5',
    ])
    after = snapshot_repo_files()
    summary_path = bench_root / 'ts_rank_candidate_benchmark_summary.json'
    summary = read_json(summary_path) if summary_path.exists() else {}
    alpha_cases = [case for case in summary.get('cases', []) if str(case.get('case', '')).startswith('alpha017_sample')]
    ok = bool(
        proc.returncode == 0
        and summary.get('verdict') == 'ACCEPT'
        and alpha_cases
        and not (after - before)
    )
    return {
        'case': 'ts_rank_candidate_alpha017_sample_readonly',
        'rc': proc.returncode,
        'summary_exists': summary_path.exists(),
        'summary_verdict': summary.get('verdict'),
        'alpha_case_count': len(alpha_cases),
        'canonical_pollution': {'polluted': bool(after - before), 'new_files': sorted(after - before)},
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': ok,
    }


def run_ts_rank_candidate_non_tmp_root_blocks_case() -> dict[str, Any]:
    proc = run_cmd([
        sys.executable,
        'scripts/run_ts_rank_candidate_benchmark.py',
        '--fresh',
        '--root',
        '/Users/humphrey/tmp_factorforge_bad_ts_rank_candidates',
        '--windows',
        '5',
    ])
    token_present = 'BLOCK_NON_TMP_FACTORFORGE_ROOT' in (proc.stdout + proc.stderr)
    return {
        'case': 'ts_rank_candidate_non_tmp_root_blocks',
        'rc': proc.returncode,
        'token_present': token_present,
        'ok': bool(proc.returncode == 1 and token_present),
    }


def create_formula_ts_rank_step3b_fixture(root: Path, report_id: str) -> tuple[Path, dict[str, Any]]:
    run_dir = root / 'runs' / report_id / 'step3a_local_inputs'
    run_dir.mkdir(parents=True, exist_ok=True)
    daily = build_formula_fixture_frame(unsorted=True)
    daily_csv_path = run_dir / f'daily_input__{report_id}.csv'
    daily_parquet_path = run_dir / f'daily_input__{report_id}.parquet'
    daily.to_parquet(daily_parquet_path, index=False)
    daily.to_csv(daily_csv_path, index=False)
    formula_ir = parse_formula('rank(ts_rank(close, 5)) + rank(ts_rank(close, 5))', available_columns=list(daily.columns), raise_on_error=True)
    impl_dir = root / 'generated_code' / report_id
    impl_dir.mkdir(parents=True, exist_ok=True)
    impl = impl_dir / 'factor_impl.py'
    impl.write_text(generate_pandas_formula_code(report_id=report_id, factor_id='TS_RANK_ENGINE', formula_ir=formula_ir), encoding='utf-8')
    local_inputs = {
        'input_mode': 'daily_only',
        'daily_df_parquet': str(daily_parquet_path),
        'daily_df_csv': str(daily_csv_path),
        'preferred_daily_format': 'parquet',
        'audit_daily_format': 'csv',
        'daily_io_contract': {
            'version': 'factorforge_step3a_daily_io_contract_v1',
            'performance_path': 'parquet',
            'audit_path': 'csv',
            'csv_required_for_audit': True,
            'parquet_required_for_performance': True,
        },
    }
    return impl, local_inputs


def run_step3b_ts_rank_engine_case(root: Path, report_id: str, env: dict[str, str | None], *, ts_rank_engine: str | None = None) -> dict[str, Any]:
    impl, local_inputs = create_formula_ts_rank_step3b_fixture(root, report_id)
    module = import_run_step3b(root)
    with temporary_envs(env):
        try:
            outputs = module.generate_first_run_factor_values(
                report_id=report_id,
                factor_id='TS_RANK_ENGINE',
                implementation_path=impl,
                local_inputs=local_inputs,
                step2_research_context={'smoke': True},
                mode_decision={'implementation_mode': 'operator'},
                artifact_identity={},
                ts_rank_engine=ts_rank_engine,
            )
            metadata = read_json(root / outputs['run_metadata_path'])
            return {'rc': 0, 'metadata': metadata, 'error': None}
        except SystemExit as exc:
            return {'rc': 1, 'metadata': {}, 'error': str(exc)}


def run_ts_rank_engine_default_is_pandas_case(root: Path) -> dict[str, Any]:
    result = run_step3b_ts_rank_engine_case(
        root,
        'PERF_SMOKE_TS_RANK_ENGINE_DEFAULT',
        {
            'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': None,
            'FACTORFORGE_TS_RANK_ENGINE': None,
            'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_FAST': None,
            'FACTORFORGE_EXPERIMENTAL_TS_RANK_MAX_SECONDS': None,
            'FACTORFORGE_TS_RANK_ENGINE_FAULT_INJECTION': None,
        },
    )
    engine_profile = (((result.get('metadata') or {}).get('performance_profile') or {}).get('formula_engine_profile') or {})
    ts_profile = engine_profile.get('ts_rank_engine_profile') or {}
    kernel_profile = engine_profile.get('kernel_profile') or {}
    ok = bool(
        result.get('rc') == 0
        and ts_profile.get('selected_engine') == 'pandas_reference'
        and ts_profile.get('experimental_enabled') is False
        and int(ts_profile.get('engine_call_count') or 0) == 0
        and int(engine_profile.get('ts_rank_fast_path_count') or 0) == 0
        and ((kernel_profile.get('default_numpy_ts_profile') or {}).get('enabled') is True)
        and _optimized_count(kernel_profile, 'ts_rank') >= 1
    )
    return {'case': 'ts_rank_engine_default_is_pandas', 'ts_rank_engine_profile': ts_profile, 'engine_profile': engine_profile, 'ok': ok}


def run_ts_rank_engine_requires_explicit_enable_case(root: Path) -> dict[str, Any]:
    result = run_step3b_ts_rank_engine_case(
        root,
        'PERF_SMOKE_TS_RANK_ENGINE_REQUIRES_ENABLE',
        {
            'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': None,
            'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_FAST': None,
            'FACTORFORGE_TS_RANK_ENGINE': 'numpy_sliding_window_experimental',
        },
    )
    token_present = 'BLOCK_EXPERIMENTAL_TS_RANK_ENGINE_NOT_ENABLED' in str(result.get('error') or '')
    return {'case': 'ts_rank_engine_requires_explicit_enable', 'rc': result.get('rc'), 'token_present': token_present, 'ok': bool(result.get('rc') == 1 and token_present)}


def run_ts_rank_engine_invalid_blocks_case(root: Path) -> dict[str, Any]:
    result = run_step3b_ts_rank_engine_case(
        root,
        'PERF_SMOKE_TS_RANK_ENGINE_INVALID',
        {
            'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': '1',
            'FACTORFORGE_TS_RANK_ENGINE': 'bad_engine',
        },
    )
    token_present = 'BLOCK_EXPERIMENTAL_TS_RANK_ENGINE_INVALID' in str(result.get('error') or '')
    return {'case': 'ts_rank_engine_invalid_blocks', 'rc': result.get('rc'), 'token_present': token_present, 'ok': bool(result.get('rc') == 1 and token_present)}


def run_ts_rank_engine_experimental_parity_passes_case(root: Path) -> dict[str, Any]:
    result = run_step3b_ts_rank_engine_case(
        root,
        'PERF_SMOKE_TS_RANK_ENGINE_EXPERIMENTAL',
        {
            'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': '1',
            'FACTORFORGE_TS_RANK_ENGINE': 'numpy_sliding_window_experimental',
            'FACTORFORGE_EXPERIMENTAL_TS_RANK_MAX_SECONDS': None,
            'FACTORFORGE_TS_RANK_ENGINE_FAULT_INJECTION': None,
        },
    )
    engine_profile = (((result.get('metadata') or {}).get('performance_profile') or {}).get('formula_engine_profile') or {})
    ts_profile = engine_profile.get('ts_rank_engine_profile') or {}
    ok = bool(
        result.get('rc') == 0
        and ts_profile.get('selected_engine') == 'numpy_sliding_window_experimental'
        and ts_profile.get('experimental_enabled') is True
        and ts_profile.get('parity_checked') is True
        and float(ts_profile.get('parity_max_abs_diff') or 0.0) == 0.0
        and ts_profile.get('parity_key_order_equal') is True
        and ts_profile.get('parity_nan_mask_equal') is True
        and int(ts_profile.get('engine_call_count') or 0) > 0
    )
    return {'case': 'ts_rank_engine_experimental_parity_passes', 'ts_rank_engine_profile': ts_profile, 'ok': ok}


def run_ts_rank_engine_parity_failure_blocks_case(root: Path) -> dict[str, Any]:
    result = run_step3b_ts_rank_engine_case(
        root,
        'PERF_SMOKE_TS_RANK_ENGINE_PARITY_FAIL',
        {
            'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': '1',
            'FACTORFORGE_TS_RANK_ENGINE': 'numpy_sliding_window_experimental',
            'FACTORFORGE_TS_RANK_ENGINE_FAULT_INJECTION': '1',
        },
    )
    token_present = 'BLOCK_EXPERIMENTAL_TS_RANK_PARITY_FAILED' in str(result.get('error') or '')
    return {'case': 'ts_rank_engine_parity_failure_blocks', 'rc': result.get('rc'), 'token_present': token_present, 'ok': bool(result.get('rc') == 1 and token_present)}


def run_ts_rank_engine_runtime_guard_blocks_case(root: Path) -> dict[str, Any]:
    result = run_step3b_ts_rank_engine_case(
        root,
        'PERF_SMOKE_TS_RANK_ENGINE_RUNTIME_GUARD',
        {
            'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': '1',
            'FACTORFORGE_TS_RANK_ENGINE': 'numpy_sliding_window_experimental',
            'FACTORFORGE_EXPERIMENTAL_TS_RANK_MAX_SECONDS': '0.000001',
        },
    )
    token_present = 'BLOCK_EXPERIMENTAL_TS_RANK_RUNTIME_GUARD' in str(result.get('error') or '')
    return {'case': 'ts_rank_engine_runtime_guard_blocks', 'rc': result.get('rc'), 'token_present': token_present, 'ok': bool(result.get('rc') == 1 and token_present)}


def run_ts_rank_engine_no_default_path_drift_case() -> dict[str, Any]:
    frame = build_ts_rank_large_frame()
    stats: dict[str, Any] = {}
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': None,
        'FACTORFORGE_TS_RANK_ENGINE': None,
        'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_FAST': None,
    }):
        _result = ts_rank(frame['x'], 20, frame, stats=stats)
    profile = stats.get('ts_rank_engine_profile') or {}
    ok = bool(
        stats.get('ts_rank_engine') == 'pandas_reference'
        and stats.get('ts_rank_fast_path_enabled') is False
        and profile.get('selected_engine') == 'pandas_reference'
        and profile.get('experimental_enabled') is False
    )
    return {'case': 'ts_rank_engine_no_default_path_drift', 'stats': stats, 'ok': ok}


def run_ts_rank_legacy_fast_env_ignored_case(root: Path) -> dict[str, Any]:
    result = run_step3b_ts_rank_engine_case(
        root,
        'PERF_SMOKE_TS_RANK_LEGACY_FAST_ENV_IGNORED',
        {
            'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_FAST': '1',
            'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': None,
            'FACTORFORGE_TS_RANK_ENGINE': None,
            'FACTORFORGE_EXPERIMENTAL_TS_RANK_MAX_SECONDS': None,
            'FACTORFORGE_TS_RANK_ENGINE_FAULT_INJECTION': None,
        },
    )
    engine_profile = (((result.get('metadata') or {}).get('performance_profile') or {}).get('formula_engine_profile') or {})
    ts_profile = engine_profile.get('ts_rank_engine_profile') or {}
    kernel_profile = engine_profile.get('kernel_profile') or {}
    ok = bool(
        result.get('rc') == 0
        and ts_profile.get('selected_engine') == 'pandas_reference'
        and ts_profile.get('experimental_enabled') is False
        and ts_profile.get('legacy_fast_env_ignored') is True
        and ts_profile.get('legacy_fast_env_name') == 'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_FAST'
        and int(engine_profile.get('ts_rank_fast_path_count') or 0) == 0
        and ((kernel_profile.get('default_numpy_ts_profile') or {}).get('enabled') is True)
        and _optimized_count(kernel_profile, 'ts_rank') >= 1
    )
    return {'case': 'ts_rank_legacy_fast_env_ignored', 'ts_rank_engine_profile': ts_profile, 'engine_profile': engine_profile, 'ok': ok}


def run_ts_rank_legacy_fast_env_does_not_select_engine_with_new_gate_case(root: Path) -> dict[str, Any]:
    result = run_step3b_ts_rank_engine_case(
        root,
        'PERF_SMOKE_TS_RANK_LEGACY_FAST_ENV_WITH_NEW_GATE',
        {
            'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_FAST': '1',
            'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': '1',
            'FACTORFORGE_TS_RANK_ENGINE': None,
            'FACTORFORGE_EXPERIMENTAL_TS_RANK_MAX_SECONDS': None,
            'FACTORFORGE_TS_RANK_ENGINE_FAULT_INJECTION': None,
        },
    )
    engine_profile = (((result.get('metadata') or {}).get('performance_profile') or {}).get('formula_engine_profile') or {})
    ts_profile = engine_profile.get('ts_rank_engine_profile') or {}
    kernel_profile = engine_profile.get('kernel_profile') or {}
    ok = bool(
        result.get('rc') == 0
        and ts_profile.get('selected_engine') == 'pandas_reference'
        and int(engine_profile.get('ts_rank_fast_path_count') or 0) == 0
        and ts_profile.get('legacy_fast_env_ignored') is True
        and ((kernel_profile.get('default_numpy_ts_profile') or {}).get('enabled') is True)
        and _optimized_count(kernel_profile, 'ts_rank') >= 1
    )
    return {
        'case': 'ts_rank_legacy_fast_env_does_not_select_engine_with_new_gate',
        'ts_rank_engine_profile': ts_profile,
        'engine_profile': engine_profile,
        'ok': ok,
    }


def build_kernel_formula_frame() -> pd.DataFrame:
    rows = []
    dates = pd.bdate_range('2020-01-01', periods=12)
    for code_idx, code in enumerate(['A', 'B', 'C', 'D']):
        for day_idx, dt in enumerate(dates):
            close = float(10 + code_idx + day_idx * 0.25)
            if (code, day_idx) in {('B', 4), ('C', 7)}:
                close = np.nan
            volume = float(1000 + code_idx * 17 + day_idx * 3)
            rows.append({
                'ts_code': code,
                'trade_date': dt.strftime('%Y%m%d'),
                'close': close,
                'volume': volume,
                'pct_chg': float(code_idx * 0.001 + day_idx * 0.0001),
            })
    return pd.DataFrame(rows).iloc[[*range(2, len(rows), 4), *range(0, len(rows), 4), *range(3, len(rows), 4), *range(1, len(rows), 4)]].reset_index(drop=True)


def build_ts_rank_edge_frame() -> pd.DataFrame:
    rows = []
    dates = pd.bdate_range('2020-01-01', periods=16)
    for code in ['A', 'B', 'C', 'D']:
        for idx, dt in enumerate(dates):
            close = float((idx * 3) % 7)
            volume = float(100 + idx)
            if code == 'B' and idx in {4, 5, 6}:
                close = 3.0
            if code == 'C' and idx == 8:
                close = np.nan
            rows.append({
                'ts_code': code,
                'trade_date': dt.strftime('%Y%m%d'),
                'close': close,
                'volume': volume,
            })
    frame = pd.DataFrame(rows)
    return frame.iloc[[*range(2, len(frame), 4), *range(0, len(frame), 4), *range(3, len(frame), 4), *range(1, len(frame), 4)]].reset_index(drop=True)


def _kernel_formula_profile(formula: str, frame: pd.DataFrame, *, kernel_config: dict | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    formula_ir = parse_formula(formula, available_columns=list(frame.columns), raise_on_error=True)
    return evaluate_formula_frame(
        formula_ir,
        frame,
        engine='optimized',
        return_profile=True,
        formula_kernel_config=kernel_config,
    )


PROMOTED_NUMPY_TS_FORMULA = (
    'sum(close, 4) + mean(volume, 4) + min(close, 4) + max(volume, 4) + '
    'delta(close, 3) + delay(volume, 2) + argmin(close, 4) + argmax(volume, 4) + '
    'ts_rank(close, 5) + corr(close, volume, 4) + covariance(close, volume, 4)'
)


def _optimized_count(kernel_profile: dict[str, Any], operator: str) -> int:
    return int(((kernel_profile.get('by_operator') or {}).get(operator) or {}).get('optimized_call_count') or 0)


def _fallback_count(kernel_profile: dict[str, Any], operator: str) -> int:
    return int(((kernel_profile.get('by_operator') or {}).get(operator) or {}).get('fallback_count') or 0)


def _promoted_operator_counts_ok(kernel_profile: dict[str, Any], *, expect_optimized: bool) -> bool:
    expected = ['sum', 'mean', 'min', 'max', 'delta', 'delay', 'argmin', 'argmax', 'ts_rank', 'correlation', 'covariance']
    if expect_optimized:
        return all(_optimized_count(kernel_profile, op) >= 1 for op in expected)
    return all(_optimized_count(kernel_profile, op) == 0 and _fallback_count(kernel_profile, op) >= 1 for op in expected)


def build_corr_cov_kernel_edge_frame() -> pd.DataFrame:
    rows = []
    dates = pd.bdate_range('2020-01-02', periods=18)
    for ticker in ['POS', 'NEG', 'ZERO_LEFT', 'ZERO_RIGHT', 'NEAR_CONST', 'NAN_MIX']:
        for idx, dt in enumerate(dates):
            x = float(idx + 1)
            if ticker == 'POS':
                close, volume = x, 2.0 * x + 5.0
            elif ticker == 'NEG':
                close, volume = x, -3.0 * x + 20.0
            elif ticker == 'ZERO_LEFT':
                close, volume = 7.0, x
            elif ticker == 'ZERO_RIGHT':
                close, volume = x, -4.0
            elif ticker == 'NEAR_CONST':
                close = 1.0 + (idx % 3) * 1e-9
                volume = 2.0 + (idx % 4) * 1e-9
            elif ticker == 'NAN_MIX':
                close, volume = x, x * 0.5
                if idx in {4, 9}:
                    close = np.nan
                if idx in {6, 11}:
                    volume = np.nan
            else:
                raise ValueError(f'unknown ticker: {ticker}')
            rows.append({
                'ts_code': ticker,
                'trade_date': dt.strftime('%Y%m%d'),
                'close': close,
                'volume': volume,
            })
    frame = pd.DataFrame(rows)
    order = [*range(2, len(frame), 7), *range(0, len(frame), 7), *range(5, len(frame), 7), *range(1, len(frame), 7), *range(4, len(frame), 7), *range(3, len(frame), 7), *range(6, len(frame), 7)]
    return frame.iloc[order].reset_index(drop=True)


def run_formula_kernel_default_path_remains_pandas_case() -> dict[str, Any]:
    frame = build_kernel_formula_frame()
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
        'FACTORFORGE_FORMULA_KERNEL_ENGINE': None,
        'FACTORFORGE_EXPERIMENTAL_FORMULA_KERNEL_MAX_SECONDS': None,
        'FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL': None,
    }):
        kernel_config = resolve_formula_kernel_engine()
        _out, profile = _kernel_formula_profile('mean(close, 3) + sum(volume, 3)', frame, kernel_config=kernel_config)
    kernel_profile = profile.get('kernel_profile') or {}
    default_profile = kernel_profile.get('default_numpy_ts_profile') or {}
    ok = bool(
        kernel_config.get('selected_engine') == 'pandas_optimized'
        and kernel_profile.get('selected_engine') == 'pandas_optimized'
        and kernel_profile.get('experimental_enabled') is False
        and kernel_profile.get('safe_to_make_default') is False
        and int(kernel_profile.get('operator_call_count') or 0) >= 2
        and default_profile.get('enabled') is True
        and _optimized_count(kernel_profile, 'mean') >= 1
        and _optimized_count(kernel_profile, 'sum') >= 1
    )
    return {'case': 'formula_kernel_default_path_remains_pandas', 'kernel_profile': kernel_profile, 'ok': ok}


def run_formula_kernel_requires_explicit_enable_case() -> dict[str, Any]:
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
        'FACTORFORGE_FORMULA_KERNEL_ENGINE': 'numpy_rolling_experimental',
    }):
        try:
            resolve_formula_kernel_engine()
            error = ''
        except ValueError as exc:
            error = str(exc)
    token_present = 'BLOCK_EXPERIMENTAL_FORMULA_KERNEL_NOT_ENABLED' in error
    return {'case': 'formula_kernel_requires_explicit_enable', 'token_present': token_present, 'ok': bool(token_present)}


def run_formula_kernel_invalid_engine_blocks_case() -> dict[str, Any]:
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': '1',
        'FACTORFORGE_FORMULA_KERNEL_ENGINE': 'bad_kernel',
    }):
        try:
            resolve_formula_kernel_engine()
            error = ''
        except ValueError as exc:
            error = str(exc)
    token_present = 'BLOCK_EXPERIMENTAL_FORMULA_KERNEL_INVALID' in error
    return {'case': 'formula_kernel_invalid_engine_blocks', 'token_present': token_present, 'ok': bool(token_present)}


def run_formula_kernel_rolling_mean_sum_parity_case() -> dict[str, Any]:
    frame = build_kernel_formula_frame()
    formula_ir = parse_formula('mean(close, 3) + sum(volume, 3)', available_columns=list(frame.columns), raise_on_error=True)
    reference = evaluate_formula_frame(formula_ir, frame, engine='reference')
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': '1',
        'FACTORFORGE_FORMULA_KERNEL_ENGINE': 'numpy_rolling_experimental',
    }):
        kernel_config = resolve_formula_kernel_engine()
        candidate, profile = evaluate_formula_frame(
            formula_ir,
            frame,
            engine='optimized',
            return_profile=True,
            formula_kernel_config=kernel_config,
        )
    parity = assert_polars_result_parity(reference, candidate, tolerance=1e-12)
    kernel_profile = profile.get('kernel_profile') or {}
    ok = bool(
        parity.get('nan_mask_equal') is True
        and float(parity.get('max_abs_diff') or 0.0) <= 1e-12
        and kernel_profile.get('selected_engine') == 'numpy_rolling_experimental'
        and int((kernel_profile.get('by_operator') or {}).get('mean', {}).get('optimized_call_count') or 0) >= 1
        and int((kernel_profile.get('by_operator') or {}).get('sum', {}).get('optimized_call_count') or 0) >= 1
    )
    return {'case': 'formula_kernel_rolling_mean_sum_parity', 'kernel_profile': kernel_profile, **parity, 'ok': ok}


def run_formula_kernel_rolling_std_parity_case() -> dict[str, Any]:
    frame = build_kernel_formula_frame()
    formula_ir = parse_formula('std(close, 3)', available_columns=list(frame.columns), raise_on_error=True)
    reference = evaluate_formula_frame(formula_ir, frame, engine='reference')
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': '1',
        'FACTORFORGE_FORMULA_KERNEL_ENGINE': 'numpy_rolling_experimental',
    }):
        kernel_config = resolve_formula_kernel_engine()
        candidate, profile = evaluate_formula_frame(
            formula_ir,
            frame,
            engine='optimized',
            return_profile=True,
            formula_kernel_config=kernel_config,
        )
    parity = assert_polars_result_parity(reference, candidate, tolerance=1e-12)
    kernel_profile = profile.get('kernel_profile') or {}
    ok = bool(parity.get('nan_mask_equal') is True and float(parity.get('max_abs_diff') or 0.0) <= 1e-12)
    return {'case': 'formula_kernel_rolling_std_parity', 'kernel_profile': kernel_profile, **parity, 'ok': ok}


def run_formula_kernel_ts_rank_candidate_parity_case() -> dict[str, Any]:
    frame = build_kernel_formula_frame()
    formula_ir = parse_formula('ts_rank(close, 4)', available_columns=list(frame.columns), raise_on_error=True)
    reference = evaluate_formula_frame(formula_ir, frame, engine='reference')
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': '1',
        'FACTORFORGE_FORMULA_KERNEL_ENGINE': 'numpy_rolling_experimental',
    }):
        kernel_config = resolve_formula_kernel_engine()
        candidate, profile = evaluate_formula_frame(
            formula_ir,
            frame,
            engine='optimized',
            return_profile=True,
            formula_kernel_config=kernel_config,
        )
    parity = assert_polars_result_parity(reference, candidate, tolerance=1e-12)
    kernel_profile = profile.get('kernel_profile') or {}
    ok = bool(parity.get('nan_mask_equal') is True and float(parity.get('max_abs_diff') or 0.0) <= 1e-12)
    return {'case': 'formula_kernel_ts_rank_candidate_parity', 'kernel_profile': kernel_profile, **parity, 'ok': ok}


def run_formula_kernel_ts_rank_edge_parity_case() -> dict[str, Any]:
    frame = build_ts_rank_edge_frame()
    formula_ir = parse_formula('ts_rank(close, 5)', available_columns=list(frame.columns), raise_on_error=True)
    reference = evaluate_formula_frame(formula_ir, frame, engine='reference')
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': '1',
        'FACTORFORGE_FORMULA_KERNEL_ENGINE': 'numpy_rolling_experimental',
        'FACTORFORGE_FORMULA_KERNEL_FAULT_INJECTION': None,
        'FACTORFORGE_TS_RANK_ENGINE': None,
        'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': None,
    }):
        kernel_config = resolve_formula_kernel_engine()
        candidate, profile = evaluate_formula_frame(
            formula_ir,
            frame,
            engine='optimized',
            return_profile=True,
            formula_kernel_config=kernel_config,
        )
    parity = assert_polars_result_parity(reference, candidate, tolerance=1e-12)
    kernel_profile = profile.get('kernel_profile') or {}
    by_operator = kernel_profile.get('by_operator') or {}
    ok = bool(
        parity.get('row_count_equal') is True
        and parity.get('key_order_equal') is True
        and parity.get('nan_mask_equal') is True
        and float(parity.get('max_abs_diff') or 0.0) <= 1e-12
        and kernel_profile.get('selected_engine') == 'numpy_rolling_experimental'
        and kernel_profile.get('experimental_enabled') is True
        and int((by_operator.get('ts_rank') or {}).get('optimized_call_count') or 0) >= 1
        and kernel_profile.get('safe_to_make_default') is False
    )
    return {'case': 'formula_kernel_ts_rank_edge_parity', 'kernel_profile': kernel_profile, **parity, 'ok': ok}


def run_formula_kernel_ts_rank_default_path_unchanged_case() -> dict[str, Any]:
    frame = build_ts_rank_edge_frame()
    formula_ir = parse_formula('ts_rank(close, 5)', available_columns=list(frame.columns), raise_on_error=True)
    reference = evaluate_formula_frame(formula_ir, frame, engine='reference')
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
        'FACTORFORGE_FORMULA_KERNEL_ENGINE': None,
        'FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL': None,
        'FACTORFORGE_TS_RANK_ENGINE': None,
        'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': None,
    }):
        kernel_config = resolve_formula_kernel_engine()
        candidate, profile = evaluate_formula_frame(
            formula_ir,
            frame,
            engine='optimized',
            return_profile=True,
            formula_kernel_config=kernel_config,
        )
    parity = assert_polars_result_parity(reference, candidate, tolerance=1e-12)
    kernel_profile = profile.get('kernel_profile') or {}
    ts_profile = profile.get('ts_rank_engine_profile') or {}
    by_operator = kernel_profile.get('by_operator') or {}
    default_profile = kernel_profile.get('default_numpy_ts_profile') or {}
    ok = bool(
        parity.get('row_count_equal') is True
        and parity.get('key_order_equal') is True
        and parity.get('nan_mask_equal') is True
        and float(parity.get('max_abs_diff') or 0.0) <= 1e-12
        and kernel_profile.get('selected_engine') == 'pandas_optimized'
        and kernel_profile.get('experimental_enabled') is False
        and default_profile.get('enabled') is True
        and int((by_operator.get('ts_rank') or {}).get('optimized_call_count') or 0) >= 1
        and not ts_profile
    )
    return {'case': 'formula_kernel_ts_rank_default_path_unchanged', 'kernel_profile': kernel_profile, 'ts_rank_engine_profile': ts_profile, **parity, 'ok': ok}


def run_formula_kernel_ts_rank_engine_gate_coexists_case() -> dict[str, Any]:
    frame = build_ts_rank_edge_frame()
    formula_ir = parse_formula('ts_rank(close, 5)', available_columns=list(frame.columns), raise_on_error=True)
    reference = evaluate_formula_frame(formula_ir, frame, engine='reference')
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
        'FACTORFORGE_FORMULA_KERNEL_ENGINE': None,
        'FACTORFORGE_TS_RANK_ENGINE': 'numpy_sliding_window_experimental',
        'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': '1',
        'FACTORFORGE_EXPERIMENTAL_TS_RANK_MAX_SECONDS': None,
    }):
        kernel_config = resolve_formula_kernel_engine()
        ts_rank_config = resolve_ts_rank_engine()
        candidate, profile = evaluate_formula_frame(
            formula_ir,
            frame,
            engine='optimized',
            return_profile=True,
            ts_rank_engine_config=ts_rank_config,
            formula_kernel_config=kernel_config,
        )
    parity = assert_polars_result_parity(reference, candidate, tolerance=1e-12)
    kernel_profile = profile.get('kernel_profile') or {}
    ts_profile = profile.get('ts_rank_engine_profile') or {}
    by_operator = kernel_profile.get('by_operator') or {}
    ok = bool(
        parity.get('row_count_equal') is True
        and parity.get('key_order_equal') is True
        and parity.get('nan_mask_equal') is True
        and float(parity.get('max_abs_diff') or 0.0) <= 1e-12
        and kernel_profile.get('selected_engine') == 'pandas_optimized'
        and int((by_operator.get('ts_rank') or {}).get('optimized_call_count') or 0) == 0
        and ts_profile.get('selected_engine') == 'numpy_sliding_window_experimental'
        and ts_profile.get('experimental_enabled') is True
    )
    return {'case': 'formula_kernel_ts_rank_engine_gate_coexists', 'kernel_profile': kernel_profile, 'ts_rank_engine_profile': ts_profile, **parity, 'ok': ok}


def run_formula_kernel_argmin_argmax_parity_case() -> dict[str, Any]:
    frame = build_kernel_formula_frame()
    formula_ir = parse_formula('argmin(close, 4) + argmax(volume, 4)', available_columns=list(frame.columns), raise_on_error=True)
    reference = evaluate_formula_frame(formula_ir, frame, engine='reference')
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': '1',
        'FACTORFORGE_FORMULA_KERNEL_ENGINE': 'numpy_rolling_experimental',
        'FACTORFORGE_FORMULA_KERNEL_FAULT_INJECTION': None,
    }):
        kernel_config = resolve_formula_kernel_engine()
        candidate, profile = evaluate_formula_frame(
            formula_ir,
            frame,
            engine='optimized',
            return_profile=True,
            formula_kernel_config=kernel_config,
        )
    parity = assert_polars_result_parity(reference, candidate, tolerance=1e-12)
    kernel_profile = profile.get('kernel_profile') or {}
    by_operator = kernel_profile.get('by_operator') or {}
    ok = bool(
        parity.get('nan_mask_equal') is True
        and float(parity.get('max_abs_diff') or 0.0) <= 1e-12
        and int((by_operator.get('argmin') or {}).get('optimized_call_count') or 0) >= 1
        and int((by_operator.get('argmax') or {}).get('optimized_call_count') or 0) >= 1
        and kernel_profile.get('safe_to_make_default') is False
    )
    return {'case': 'formula_kernel_argmin_argmax_parity', 'kernel_profile': kernel_profile, **parity, 'ok': ok}


def run_formula_kernel_argmin_argmax_default_path_unchanged_case() -> dict[str, Any]:
    frame = build_kernel_formula_frame()
    formula_ir = parse_formula('argmin(close, 4) + argmax(volume, 4)', available_columns=list(frame.columns), raise_on_error=True)
    reference = evaluate_formula_frame(formula_ir, frame, engine='reference')
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
        'FACTORFORGE_FORMULA_KERNEL_ENGINE': None,
        'FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL': None,
        'FACTORFORGE_FORMULA_KERNEL_FAULT_INJECTION': None,
    }):
        kernel_config = resolve_formula_kernel_engine()
        candidate, profile = evaluate_formula_frame(
            formula_ir,
            frame,
            engine='optimized',
            return_profile=True,
            formula_kernel_config=kernel_config,
        )
    parity = assert_polars_result_parity(reference, candidate, tolerance=1e-12)
    kernel_profile = profile.get('kernel_profile') or {}
    by_operator = kernel_profile.get('by_operator') or {}
    default_profile = kernel_profile.get('default_numpy_ts_profile') or {}
    ok = bool(
        parity.get('nan_mask_equal') is True
        and float(parity.get('max_abs_diff') or 0.0) <= 1e-12
        and kernel_profile.get('selected_engine') == 'pandas_optimized'
        and kernel_profile.get('experimental_enabled') is False
        and default_profile.get('enabled') is True
        and int((by_operator.get('argmin') or {}).get('optimized_call_count') or 0) >= 1
        and int((by_operator.get('argmax') or {}).get('optimized_call_count') or 0) >= 1
    )
    return {'case': 'formula_kernel_argmin_argmax_default_path_unchanged', 'kernel_profile': kernel_profile, **parity, 'ok': ok}


def run_formula_kernel_default_numpy_ts_promoted_parity_case() -> dict[str, Any]:
    frame = build_ts_rank_edge_frame()
    formula_ir = parse_formula(PROMOTED_NUMPY_TS_FORMULA, available_columns=list(frame.columns), raise_on_error=True)
    reference = evaluate_formula_frame(formula_ir, frame, engine='reference')
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
        'FACTORFORGE_FORMULA_KERNEL_ENGINE': None,
        'FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL': None,
        'FACTORFORGE_TS_RANK_ENGINE': None,
        'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': None,
        'FACTORFORGE_FORMULA_KERNEL_FAULT_INJECTION': None,
    }):
        kernel_config = resolve_formula_kernel_engine()
        candidate, profile = evaluate_formula_frame(
            formula_ir,
            frame,
            engine='optimized',
            return_profile=True,
            formula_kernel_config=kernel_config,
        )
    parity = assert_polars_result_parity(reference, candidate, tolerance=1e-12)
    kernel_profile = profile.get('kernel_profile') or {}
    default_profile = kernel_profile.get('default_numpy_ts_profile') or {}
    ok = bool(
        parity.get('row_count_equal') is True
        and parity.get('key_order_equal') is True
        and parity.get('nan_mask_equal') is True
        and float(parity.get('max_abs_diff') or 0.0) <= 1e-12
        and kernel_profile.get('selected_engine') == 'pandas_optimized'
        and kernel_profile.get('experimental_enabled') is False
        and default_profile.get('enabled') is True
        and set(default_profile.get('operators') or []) == set(DEFAULT_NUMPY_TS_OPERATORS)
        and set(DEFAULT_NUMPY_TS_EXCLUDED_OPERATORS).issubset(set(default_profile.get('excluded_operators') or []))
        and _promoted_operator_counts_ok(kernel_profile, expect_optimized=True)
        and kernel_profile.get('safe_to_make_default') is False
    )
    return {'case': 'formula_kernel_default_numpy_ts_promoted_parity', 'kernel_profile': kernel_profile, **parity, 'ok': ok}


def run_formula_kernel_default_numpy_ts_direct_caller_promoted_case() -> dict[str, Any]:
    frame = build_ts_rank_edge_frame()
    formula_ir = parse_formula(PROMOTED_NUMPY_TS_FORMULA, available_columns=list(frame.columns), raise_on_error=True)
    reference = evaluate_formula_frame(formula_ir, frame, engine='reference')
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
        'FACTORFORGE_FORMULA_KERNEL_ENGINE': None,
        'FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL': None,
        'FACTORFORGE_TS_RANK_ENGINE': None,
        'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': None,
        'FACTORFORGE_FORMULA_KERNEL_FAULT_INJECTION': None,
    }):
        candidate, profile = evaluate_formula_frame(
            formula_ir,
            frame,
            engine='optimized',
            return_profile=True,
        )
    parity = assert_polars_result_parity(reference, candidate, tolerance=1e-12)
    kernel_profile = profile.get('kernel_profile') or {}
    default_profile = kernel_profile.get('default_numpy_ts_profile') or {}
    ts_profile = profile.get('ts_rank_engine_profile') or {}
    ok = bool(
        parity.get('row_count_equal') is True
        and parity.get('key_order_equal') is True
        and parity.get('nan_mask_equal') is True
        and float(parity.get('max_abs_diff') or 0.0) <= 1e-12
        and kernel_profile.get('selected_engine') == 'pandas_optimized'
        and kernel_profile.get('experimental_enabled') is False
        and default_profile.get('enabled') is True
        and _promoted_operator_counts_ok(kernel_profile, expect_optimized=True)
        and not ts_profile
    )
    return {'case': 'formula_kernel_default_numpy_ts_direct_caller_promoted', 'kernel_profile': kernel_profile, 'ts_rank_engine_profile': ts_profile, **parity, 'ok': ok}


def run_formula_kernel_default_numpy_ts_rollback_env_restores_pandas_case() -> dict[str, Any]:
    frame = build_ts_rank_edge_frame()
    formula_ir = parse_formula(PROMOTED_NUMPY_TS_FORMULA, available_columns=list(frame.columns), raise_on_error=True)
    reference = evaluate_formula_frame(formula_ir, frame, engine='reference')
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
        'FACTORFORGE_FORMULA_KERNEL_ENGINE': None,
        'FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL': '1',
        'FACTORFORGE_TS_RANK_ENGINE': None,
        'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': None,
        'FACTORFORGE_FORMULA_KERNEL_FAULT_INJECTION': None,
    }):
        kernel_config = resolve_formula_kernel_engine()
        candidate, profile = evaluate_formula_frame(
            formula_ir,
            frame,
            engine='optimized',
            return_profile=True,
            formula_kernel_config=kernel_config,
        )
    parity = assert_polars_result_parity(reference, candidate, tolerance=1e-12)
    kernel_profile = profile.get('kernel_profile') or {}
    default_profile = kernel_profile.get('default_numpy_ts_profile') or {}
    fallback_reasons = kernel_profile.get('fallback_reasons') or []
    ok = bool(
        parity.get('row_count_equal') is True
        and parity.get('key_order_equal') is True
        and parity.get('nan_mask_equal') is True
        and float(parity.get('max_abs_diff') or 0.0) <= 1e-12
        and kernel_profile.get('selected_engine') == 'pandas_optimized'
        and kernel_profile.get('experimental_enabled') is False
        and default_profile.get('enabled') is False
        and 'default_numpy_ts_disabled' in fallback_reasons
        and _promoted_operator_counts_ok(kernel_profile, expect_optimized=False)
    )
    return {'case': 'formula_kernel_default_numpy_ts_rollback_env_restores_pandas', 'kernel_profile': kernel_profile, **parity, 'ok': ok}


def run_formula_kernel_default_numpy_ts_std_excluded_case() -> dict[str, Any]:
    frame = build_kernel_formula_frame()
    formula_ir = parse_formula('std(close, 4)', available_columns=list(frame.columns), raise_on_error=True)
    reference = evaluate_formula_frame(formula_ir, frame, engine='reference')
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
        'FACTORFORGE_FORMULA_KERNEL_ENGINE': None,
        'FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL': None,
    }):
        kernel_config = resolve_formula_kernel_engine()
        candidate, profile = evaluate_formula_frame(
            formula_ir,
            frame,
            engine='optimized',
            return_profile=True,
            formula_kernel_config=kernel_config,
        )
    parity = assert_polars_result_parity(reference, candidate, tolerance=1e-12)
    kernel_profile = profile.get('kernel_profile') or {}
    default_profile = kernel_profile.get('default_numpy_ts_profile') or {}
    by_operator = kernel_profile.get('by_operator') or {}
    std_bucket = by_operator.get('std') or by_operator.get('stddev') or {}
    ok = bool(
        parity.get('row_count_equal') is True
        and parity.get('key_order_equal') is True
        and parity.get('nan_mask_equal') is True
        and float(parity.get('max_abs_diff') or 0.0) <= 1e-12
        and int(std_bucket.get('optimized_call_count') or 0) == 0
        and int(std_bucket.get('fallback_count') or 0) >= 1
        and {'std', 'stddev'}.issubset(set(default_profile.get('excluded_operators') or []))
    )
    return {'case': 'formula_kernel_default_numpy_ts_std_excluded', 'kernel_profile': kernel_profile, **parity, 'ok': ok}


def run_formula_kernel_default_numpy_ts_corr_cov_promoted_case() -> dict[str, Any]:
    frame = build_corr_cov_kernel_edge_frame()
    formula_ir = parse_formula('corr(close, volume, 4) + covariance(close, volume, 4)', available_columns=list(frame.columns), raise_on_error=True)
    reference = evaluate_formula_frame(formula_ir, frame, engine='reference')
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
        'FACTORFORGE_FORMULA_KERNEL_ENGINE': None,
        'FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL': None,
    }):
        kernel_config = resolve_formula_kernel_engine()
        candidate, profile = evaluate_formula_frame(
            formula_ir,
            frame,
            engine='optimized',
            return_profile=True,
            formula_kernel_config=kernel_config,
        )
    parity = assert_polars_result_parity(reference, candidate, tolerance=1e-10)
    kernel_profile = profile.get('kernel_profile') or {}
    default_profile = kernel_profile.get('default_numpy_ts_profile') or {}
    by_operator = kernel_profile.get('by_operator') or {}
    ok = bool(
        parity.get('row_count_equal') is True
        and parity.get('key_order_equal') is True
        and parity.get('nan_mask_equal') is True
        and float(parity.get('max_abs_diff') or 0.0) <= 1e-10
        and default_profile.get('enabled') is True
        and int((by_operator.get('correlation') or {}).get('optimized_call_count') or 0) >= 1
        and int((by_operator.get('covariance') or {}).get('optimized_call_count') or 0) >= 1
        and 'correlation' in set(default_profile.get('operators') or [])
        and 'covariance' in set(default_profile.get('operators') or [])
        and 'correlation' not in set(default_profile.get('excluded_operators') or [])
        and 'covariance' not in set(default_profile.get('excluded_operators') or [])
    )
    return {'case': 'formula_kernel_default_numpy_ts_corr_cov_promoted', 'kernel_profile': kernel_profile, **parity, 'ok': ok}


def run_formula_kernel_default_numpy_ts_corr_cov_speed_guard_case() -> dict[str, Any]:
    rng = np.random.default_rng(7707)
    ticker_count = 500
    rows_per_ticker = 100
    row_count = ticker_count * rows_per_ticker
    base = rng.normal(size=row_count)
    frame = pd.DataFrame({
        'ts_code': np.repeat([f'S{i:05d}' for i in range(ticker_count)], rows_per_ticker),
        'trade_date': np.tile(np.arange(rows_per_ticker), ticker_count).astype(str),
        'close': base,
        'volume': 0.25 * base + rng.normal(size=row_count),
    })
    formula_ir = parse_formula('corr(close, volume, 10) + covariance(close, volume, 10)', available_columns=list(frame.columns), raise_on_error=True)
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
        'FACTORFORGE_FORMULA_KERNEL_ENGINE': None,
        'FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL': None,
    }):
        started = time.perf_counter()
        candidate, profile = evaluate_formula_frame(
            formula_ir,
            frame,
            engine='optimized',
            return_profile=True,
            formula_kernel_config=resolve_formula_kernel_engine(),
        )
        default_seconds = time.perf_counter() - started
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
        'FACTORFORGE_FORMULA_KERNEL_ENGINE': None,
        'FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL': '1',
    }):
        started = time.perf_counter()
        fallback, fallback_profile = evaluate_formula_frame(
            formula_ir,
            frame,
            engine='optimized',
            return_profile=True,
            formula_kernel_config=resolve_formula_kernel_engine(),
        )
        fallback_seconds = time.perf_counter() - started
    parity = assert_polars_result_parity(fallback, candidate, tolerance=1e-10)
    speedup = float(fallback_seconds / default_seconds) if default_seconds > 0 else 0.0
    kernel_profile = profile.get('kernel_profile') or {}
    fallback_kernel_profile = fallback_profile.get('kernel_profile') or {}
    ok = bool(
        parity.get('row_count_equal') is True
        and parity.get('key_order_equal') is True
        and parity.get('nan_mask_equal') is True
        and float(parity.get('max_abs_diff') or 0.0) <= 1e-10
        and _optimized_count(kernel_profile, 'correlation') >= 1
        and _optimized_count(kernel_profile, 'covariance') >= 1
        and _fallback_count(fallback_kernel_profile, 'correlation') >= 1
        and _fallback_count(fallback_kernel_profile, 'covariance') >= 1
        and speedup >= 1.1
    )
    return {
        'case': 'formula_kernel_default_numpy_ts_corr_cov_speed_guard',
        'rows': row_count,
        'tickers': ticker_count,
        'default_seconds': default_seconds,
        'fallback_seconds': fallback_seconds,
        'speedup_vs_pandas_fallback': speedup,
        'kernel_profile': kernel_profile,
        'fallback_kernel_profile': fallback_kernel_profile,
        **parity,
        'ok': ok,
    }


def run_formula_kernel_corr_cov_single_group_rollback_case() -> dict[str, Any]:
    frame = pd.DataFrame({
        'ts_code': ['SINGLE'] * 8,
        'trade_date': [f'2020010{i}' for i in range(1, 9)],
        'close': [1.0, 2.0, 4.0, 7.0, 11.0, 16.0, 22.0, 29.0],
        'volume': [3.0, 1.0, 5.0, 4.0, 10.0, 8.0, 13.0, 21.0],
    })
    formula_ir = parse_formula(
        'corr(close, volume, 3) + covariance(close, volume, 3) + std(close, 3)',
        available_columns=list(frame.columns),
        raise_on_error=True,
    )
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
        'FACTORFORGE_FORMULA_KERNEL_ENGINE': None,
        'FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL': None,
    }):
        default_candidate, default_profile = evaluate_formula_frame(
            formula_ir,
            frame,
            engine='optimized',
            return_profile=True,
            formula_kernel_config=resolve_formula_kernel_engine(),
        )
    rollback_error = None
    rollback_candidate = None
    rollback_profile: dict[str, Any] = {}
    with temporary_envs({
        'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
        'FACTORFORGE_FORMULA_KERNEL_ENGINE': None,
        'FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL': '1',
    }):
        try:
            rollback_candidate, rollback_profile = evaluate_formula_frame(
                formula_ir,
                frame,
                engine='optimized',
                return_profile=True,
                formula_kernel_config=resolve_formula_kernel_engine(),
            )
        except Exception as exc:  # pragma: no cover - failure payload for smoke diagnostics
            rollback_error = f'{type(exc).__name__}: {exc}'
    parity = (
        assert_polars_result_parity(default_candidate, rollback_candidate, tolerance=1e-10)
        if rollback_candidate is not None
        else {'row_count_equal': False, 'key_order_equal': False, 'nan_mask_equal': False, 'max_abs_diff': None}
    )
    default_kernel_profile = default_profile.get('kernel_profile') or {}
    rollback_kernel_profile = rollback_profile.get('kernel_profile') or {}
    ok = bool(
        rollback_error is None
        and parity.get('row_count_equal') is True
        and parity.get('key_order_equal') is True
        and parity.get('nan_mask_equal') is True
        and float(parity.get('max_abs_diff') or 0.0) <= 1e-10
        and _optimized_count(default_kernel_profile, 'correlation') >= 1
        and _optimized_count(default_kernel_profile, 'covariance') >= 1
        and _fallback_count(rollback_kernel_profile, 'correlation') >= 1
        and _fallback_count(rollback_kernel_profile, 'covariance') >= 1
        and (_fallback_count(rollback_kernel_profile, 'std') + _fallback_count(rollback_kernel_profile, 'stddev')) >= 1
    )
    return {
        'case': 'formula_kernel_corr_cov_single_group_rollback',
        'rollback_error': rollback_error,
        'default_kernel_profile': default_kernel_profile,
        'rollback_kernel_profile': rollback_kernel_profile,
        **parity,
        'ok': ok,
    }


def run_formula_kernel_parity_failure_blocks_case(root: Path) -> dict[str, Any]:
    result = run_step3b_formula_kernel_case(
        root,
        'PERF_SMOKE_FORMULA_KERNEL_PARITY_FAIL',
        formula='mean(close, 3) + sum(volume, 3)',
        env={
            'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': '1',
            'FACTORFORGE_FORMULA_KERNEL_ENGINE': 'numpy_rolling_experimental',
            'FACTORFORGE_FORMULA_KERNEL_FAULT_INJECTION': '1',
        },
    )
    token_present = 'BLOCK_EXPERIMENTAL_FORMULA_KERNEL_PARITY_FAILED' in str(result.get('error') or '')
    return {'case': 'formula_kernel_parity_failure_blocks', 'rc': result.get('rc'), 'token_present': token_present, 'ok': bool(result.get('rc') == 1 and token_present)}


def run_formula_kernel_argmin_argmax_parity_failure_blocks_case(root: Path) -> dict[str, Any]:
    result = run_step3b_formula_kernel_case(
        root,
        'PERF_SMOKE_FORMULA_KERNEL_ARGMIN_ARGMAX_PARITY_FAIL',
        formula='argmin(close, 4) + argmax(volume, 4)',
        env={
            'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': '1',
            'FACTORFORGE_FORMULA_KERNEL_ENGINE': 'numpy_rolling_experimental',
            'FACTORFORGE_FORMULA_KERNEL_FAULT_INJECTION': '1',
        },
    )
    token_present = 'BLOCK_EXPERIMENTAL_FORMULA_KERNEL_PARITY_FAILED' in str(result.get('error') or '')
    return {'case': 'formula_kernel_argmin_argmax_parity_failure_blocks', 'rc': result.get('rc'), 'token_present': token_present, 'ok': bool(result.get('rc') == 1 and token_present)}


def run_formula_kernel_ts_rank_parity_failure_blocks_case(root: Path) -> dict[str, Any]:
    result = run_step3b_formula_kernel_case(
        root,
        'PERF_SMOKE_FORMULA_KERNEL_TS_RANK_PARITY_FAIL',
        formula='ts_rank(close, 5)',
        env={
            'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': '1',
            'FACTORFORGE_FORMULA_KERNEL_ENGINE': 'numpy_rolling_experimental',
            'FACTORFORGE_FORMULA_KERNEL_FAULT_INJECTION': '1',
        },
    )
    token_present = 'BLOCK_EXPERIMENTAL_FORMULA_KERNEL_PARITY_FAILED' in str(result.get('error') or '')
    return {'case': 'formula_kernel_ts_rank_parity_failure_blocks', 'rc': result.get('rc'), 'token_present': token_present, 'ok': bool(result.get('rc') == 1 and token_present)}


def run_formula_kernel_runtime_guard_blocks_case(root: Path) -> dict[str, Any]:
    result = run_step3b_formula_kernel_case(
        root,
        'PERF_SMOKE_FORMULA_KERNEL_RUNTIME_GUARD',
        formula='mean(close, 3) + sum(volume, 3)',
        env={
            'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': '1',
            'FACTORFORGE_FORMULA_KERNEL_ENGINE': 'numpy_rolling_experimental',
            'FACTORFORGE_EXPERIMENTAL_FORMULA_KERNEL_MAX_SECONDS': '0.000001',
        },
    )
    token_present = 'BLOCK_EXPERIMENTAL_FORMULA_KERNEL_RUNTIME_GUARD' in str(result.get('error') or '')
    return {'case': 'formula_kernel_runtime_guard_blocks', 'rc': result.get('rc'), 'token_present': token_present, 'ok': bool(result.get('rc') == 1 and token_present)}


def run_formula_kernel_ts_rank_runtime_guard_blocks_case(root: Path) -> dict[str, Any]:
    result = run_step3b_formula_kernel_case(
        root,
        'PERF_SMOKE_FORMULA_KERNEL_TS_RANK_RUNTIME_GUARD',
        formula='ts_rank(close, 5)',
        env={
            'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': '1',
            'FACTORFORGE_FORMULA_KERNEL_ENGINE': 'numpy_rolling_experimental',
            'FACTORFORGE_EXPERIMENTAL_FORMULA_KERNEL_MAX_SECONDS': '0.000001',
        },
    )
    token_present = 'BLOCK_EXPERIMENTAL_FORMULA_KERNEL_RUNTIME_GUARD' in str(result.get('error') or '')
    return {'case': 'formula_kernel_ts_rank_runtime_guard_blocks', 'rc': result.get('rc'), 'token_present': token_present, 'ok': bool(result.get('rc') == 1 and token_present)}


def run_step3b_formula_kernel_case(root: Path, report_id: str, *, formula: str, env: dict[str, str | None], formula_kernel_engine: str | None = None) -> dict[str, Any]:
    run_dir = root / 'runs' / report_id / 'step3a_local_inputs'
    run_dir.mkdir(parents=True, exist_ok=True)
    daily = build_kernel_formula_frame()
    daily_csv_path = run_dir / f'daily_input__{report_id}.csv'
    daily_parquet_path = run_dir / f'daily_input__{report_id}.parquet'
    daily.to_parquet(daily_parquet_path, index=False)
    daily.to_csv(daily_csv_path, index=False)
    formula_ir = parse_formula(formula, available_columns=list(daily.columns), raise_on_error=True)
    impl_dir = root / 'generated_code' / report_id
    impl_dir.mkdir(parents=True, exist_ok=True)
    impl = impl_dir / 'factor_impl.py'
    impl.write_text(generate_pandas_formula_code(report_id=report_id, factor_id='FORMULA_KERNEL', formula_ir=formula_ir), encoding='utf-8')
    module = import_run_step3b(root)
    with temporary_envs(env):
        try:
            outputs = module.generate_first_run_factor_values(
                report_id=report_id,
                factor_id='FORMULA_KERNEL',
                implementation_path=impl,
                local_inputs={
                    'input_mode': 'daily_only',
                    'daily_df_parquet': str(daily_parquet_path),
                    'daily_df_csv': str(daily_csv_path),
                    'preferred_daily_format': 'parquet',
                    'audit_daily_format': 'csv',
                    'daily_io_contract': {
                        'version': 'factorforge_step3a_daily_io_contract_v1',
                        'performance_path': 'parquet',
                        'audit_path': 'csv',
                        'csv_required_for_audit': True,
                        'parquet_required_for_performance': True,
                    },
                },
                step2_research_context={'smoke': True},
                mode_decision={'implementation_mode': 'operator'},
                artifact_identity={},
                formula_kernel_engine=formula_kernel_engine,
            )
            metadata = read_json(root / outputs['run_metadata_path'])
            return {'rc': 0, 'metadata': metadata, 'error': None}
        except SystemExit as exc:
            return {'rc': 1, 'metadata': {}, 'error': str(exc)}


def run_step3b_formula_kernel_metadata_present_case(root: Path) -> dict[str, Any]:
    result = run_step3b_formula_kernel_case(
        root,
        'PERF_SMOKE_STEP3B_FORMULA_KERNEL_METADATA',
        formula='mean(close, 3) + sum(volume, 3)',
        env={
            'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
            'FACTORFORGE_FORMULA_KERNEL_ENGINE': None,
        },
    )
    engine_profile = (((result.get('metadata') or {}).get('performance_profile') or {}).get('formula_engine_profile') or {})
    kernel_profile = engine_profile.get('kernel_profile') or {}
    ok = bool(
        result.get('rc') == 0
        and kernel_profile.get('version') == 'factorforge_formula_kernel_profile_v1'
        and kernel_profile.get('selected_engine') == 'pandas_optimized'
        and kernel_profile.get('experimental_enabled') is False
        and kernel_profile.get('safe_to_make_default') is False
    )
    return {'case': 'step3b_formula_kernel_metadata_present', 'kernel_profile': kernel_profile, 'ok': ok}


def run_step3b_formula_kernel_argmin_argmax_metadata_case(root: Path) -> dict[str, Any]:
    result = run_step3b_formula_kernel_case(
        root,
        'PERF_SMOKE_STEP3B_FORMULA_KERNEL_ARGMIN_ARGMAX_METADATA',
        formula='argmin(close, 4) + argmax(volume, 4)',
        env={
            'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': '1',
            'FACTORFORGE_FORMULA_KERNEL_ENGINE': 'numpy_rolling_experimental',
            'FACTORFORGE_FORMULA_KERNEL_FAULT_INJECTION': None,
        },
    )
    engine_profile = (((result.get('metadata') or {}).get('performance_profile') or {}).get('formula_engine_profile') or {})
    kernel_profile = engine_profile.get('kernel_profile') or {}
    by_operator = kernel_profile.get('by_operator') or {}
    ok = bool(
        result.get('rc') == 0
        and kernel_profile.get('version') == 'factorforge_formula_kernel_profile_v1'
        and kernel_profile.get('selected_engine') == 'numpy_rolling_experimental'
        and kernel_profile.get('experimental_enabled') is True
        and kernel_profile.get('parity_checked') is True
        and kernel_profile.get('parity_nan_mask_equal') is True
        and kernel_profile.get('parity_key_order_equal') is True
        and kernel_profile.get('safe_to_make_default') is False
        and int((by_operator.get('argmin') or {}).get('optimized_call_count') or 0) >= 1
        and int((by_operator.get('argmax') or {}).get('optimized_call_count') or 0) >= 1
    )
    return {'case': 'step3b_formula_kernel_argmin_argmax_metadata', 'rc': result.get('rc'), 'kernel_profile': kernel_profile, 'ok': ok}


def run_step3b_formula_kernel_ts_rank_metadata_case(root: Path) -> dict[str, Any]:
    result = run_step3b_formula_kernel_case(
        root,
        'PERF_SMOKE_STEP3B_FORMULA_KERNEL_TS_RANK_METADATA',
        formula='ts_rank(close, 5)',
        env={
            'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': '1',
            'FACTORFORGE_FORMULA_KERNEL_ENGINE': 'numpy_rolling_experimental',
            'FACTORFORGE_FORMULA_KERNEL_FAULT_INJECTION': None,
            'FACTORFORGE_TS_RANK_ENGINE': None,
            'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': None,
        },
    )
    engine_profile = (((result.get('metadata') or {}).get('performance_profile') or {}).get('formula_engine_profile') or {})
    kernel_profile = engine_profile.get('kernel_profile') or {}
    by_operator = kernel_profile.get('by_operator') or {}
    ok = bool(
        result.get('rc') == 0
        and kernel_profile.get('version') == 'factorforge_formula_kernel_profile_v1'
        and kernel_profile.get('selected_engine') == 'numpy_rolling_experimental'
        and kernel_profile.get('experimental_enabled') is True
        and kernel_profile.get('parity_checked') is True
        and kernel_profile.get('parity_nan_mask_equal') is True
        and kernel_profile.get('parity_key_order_equal') is True
        and kernel_profile.get('safe_to_make_default') is False
        and int((by_operator.get('ts_rank') or {}).get('optimized_call_count') or 0) >= 1
    )
    return {'case': 'step3b_formula_kernel_ts_rank_metadata', 'rc': result.get('rc'), 'kernel_profile': kernel_profile, 'ok': ok}


def run_step3b_default_numpy_ts_metadata_case(root: Path) -> dict[str, Any]:
    result = run_step3b_formula_kernel_case(
        root,
        'PERF_SMOKE_STEP3B_DEFAULT_NUMPY_TS_METADATA',
        formula=PROMOTED_NUMPY_TS_FORMULA,
        env={
            'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
            'FACTORFORGE_FORMULA_KERNEL_ENGINE': None,
            'FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL': None,
            'FACTORFORGE_TS_RANK_ENGINE': None,
            'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': None,
            'FACTORFORGE_FORMULA_KERNEL_FAULT_INJECTION': None,
        },
    )
    engine_profile = (((result.get('metadata') or {}).get('performance_profile') or {}).get('formula_engine_profile') or {})
    kernel_profile = engine_profile.get('kernel_profile') or {}
    default_profile = kernel_profile.get('default_numpy_ts_profile') or {}
    ok = bool(
        result.get('rc') == 0
        and kernel_profile.get('version') == 'factorforge_formula_kernel_profile_v1'
        and kernel_profile.get('selected_engine') == 'pandas_optimized'
        and kernel_profile.get('experimental_enabled') is False
        and default_profile.get('enabled') is True
        and _promoted_operator_counts_ok(kernel_profile, expect_optimized=True)
        and kernel_profile.get('parity_checked') is True
        and kernel_profile.get('parity_nan_mask_equal') is True
        and kernel_profile.get('parity_key_order_equal') is True
    )
    return {'case': 'step3b_default_numpy_ts_metadata', 'rc': result.get('rc'), 'kernel_profile': kernel_profile, 'ok': ok}


def run_step3b_default_numpy_ts_rollback_metadata_case(root: Path) -> dict[str, Any]:
    result = run_step3b_formula_kernel_case(
        root,
        'PERF_SMOKE_STEP3B_DEFAULT_NUMPY_TS_ROLLBACK_METADATA',
        formula=PROMOTED_NUMPY_TS_FORMULA,
        env={
            'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL': None,
            'FACTORFORGE_FORMULA_KERNEL_ENGINE': None,
            'FACTORFORGE_DISABLE_DEFAULT_NUMPY_TS_KERNEL': '1',
            'FACTORFORGE_TS_RANK_ENGINE': None,
            'FACTORFORGE_ENABLE_EXPERIMENTAL_TS_RANK_ENGINE': None,
            'FACTORFORGE_FORMULA_KERNEL_FAULT_INJECTION': None,
        },
    )
    engine_profile = (((result.get('metadata') or {}).get('performance_profile') or {}).get('formula_engine_profile') or {})
    kernel_profile = engine_profile.get('kernel_profile') or {}
    default_profile = kernel_profile.get('default_numpy_ts_profile') or {}
    ok = bool(
        result.get('rc') == 0
        and kernel_profile.get('version') == 'factorforge_formula_kernel_profile_v1'
        and kernel_profile.get('selected_engine') == 'pandas_optimized'
        and kernel_profile.get('experimental_enabled') is False
        and default_profile.get('enabled') is False
        and _promoted_operator_counts_ok(kernel_profile, expect_optimized=False)
        and kernel_profile.get('parity_checked') is True
        and kernel_profile.get('parity_nan_mask_equal') is True
        and kernel_profile.get('parity_key_order_equal') is True
        and 'default_numpy_ts_disabled' in (kernel_profile.get('fallback_reasons') or [])
    )
    return {'case': 'step3b_default_numpy_ts_rollback_metadata', 'rc': result.get('rc'), 'kernel_profile': kernel_profile, 'ok': ok}


def run_step3b_formula_engine_profile_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP3B_FORMULA_ENGINE'
    run_dir = root / 'runs' / report_id / 'step3a_local_inputs'
    run_dir.mkdir(parents=True, exist_ok=True)
    daily = build_formula_fixture_frame(unsorted=True)
    daily_csv_path = run_dir / f'daily_input__{report_id}.csv'
    daily_parquet_path = run_dir / f'daily_input__{report_id}.parquet'
    daily.to_parquet(daily_parquet_path, index=False)
    daily.to_csv(daily_csv_path, index=False)
    formula_ir = parse_formula('rank(ts_rank(close, 5)) + rank(ts_rank(close, 5))', available_columns=list(daily.columns), raise_on_error=True)
    impl_dir = root / 'generated_code' / report_id
    impl_dir.mkdir(parents=True, exist_ok=True)
    impl = impl_dir / 'factor_impl.py'
    impl.write_text(generate_pandas_formula_code(report_id=report_id, factor_id='FORMULA_ENGINE', formula_ir=formula_ir), encoding='utf-8')
    module = import_run_step3b(root)
    outputs = module.generate_first_run_factor_values(
        report_id=report_id,
        factor_id='FORMULA_ENGINE',
        implementation_path=impl,
        local_inputs={
            'input_mode': 'daily_only',
            'daily_df_parquet': str(daily_parquet_path),
            'daily_df_csv': str(daily_csv_path),
            'preferred_daily_format': 'parquet',
            'audit_daily_format': 'csv',
            'daily_io_contract': {
                'version': 'factorforge_step3a_daily_io_contract_v1',
                'performance_path': 'parquet',
                'audit_path': 'csv',
                'csv_required_for_audit': True,
                'parquet_required_for_performance': True,
            },
        },
        step2_research_context={'smoke': True},
        mode_decision={'implementation_mode': 'operator'},
        artifact_identity={},
    )
    metadata = read_json(root / outputs['run_metadata_path'])
    profile = metadata.get('performance_profile') or {}
    engine_profile = profile.get('formula_engine_profile') or {}
    kernel_profile = engine_profile.get('kernel_profile') or {}
    input_io_profile = profile.get('input_io_profile') or {}
    ok = (
        outputs.get('row_count') == len(daily)
        and engine_profile.get('engine') == 'pandas_formula_ir_optimized'
        and engine_profile.get('memoization_enabled') is True
        and (engine_profile.get('cache_hits') or 0) > 0
        and engine_profile.get('parity_checked') is True
        and engine_profile.get('max_abs_diff') == 0.0
        and ((kernel_profile.get('default_numpy_ts_profile') or {}).get('enabled') is True)
        and _optimized_count(kernel_profile, 'ts_rank') >= 1
        and engine_profile.get('ts_rank_fast_path_count') == 0
        and engine_profile.get('ts_rank_fast_path_enabled') is False
        and input_io_profile.get('daily_selected_format') == 'parquet'
        and str(input_io_profile.get('daily_selected_path') or '').endswith('.parquet')
        and profile.get('normalize_sort', {}).get('already_sorted') is True
    )
    return {
        'case': 'step3b_formula_engine_profile_present',
        'report_id': report_id,
        'engine_profile': engine_profile,
        'input_io_profile': input_io_profile,
        'normalize_sort': profile.get('normalize_sort'),
        'ok': bool(ok),
    }


def run_step3b_operator_profile_metadata_present_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP3B_OPERATOR_PROFILE'
    run_dir = root / 'runs' / report_id / 'step3a_local_inputs'
    run_dir.mkdir(parents=True, exist_ok=True)
    daily = build_formula_fixture_frame(unsorted=True)
    daily_csv_path = run_dir / f'daily_input__{report_id}.csv'
    daily_parquet_path = run_dir / f'daily_input__{report_id}.parquet'
    daily.to_parquet(daily_parquet_path, index=False)
    daily.to_csv(daily_csv_path, index=False)
    formula_ir = parse_formula('rank(delta(close, 1) * (volume / close))', available_columns=list(daily.columns), raise_on_error=True)
    impl_dir = root / 'generated_code' / report_id
    impl_dir.mkdir(parents=True, exist_ok=True)
    impl = impl_dir / 'factor_impl.py'
    impl.write_text(generate_pandas_formula_code(report_id=report_id, factor_id='OPERATOR_PROFILE', formula_ir=formula_ir), encoding='utf-8')
    module = import_run_step3b(root)
    outputs = module.generate_first_run_factor_values(
        report_id=report_id,
        factor_id='OPERATOR_PROFILE',
        implementation_path=impl,
        local_inputs={
            'input_mode': 'daily_only',
            'daily_df_parquet': str(daily_parquet_path),
            'daily_df_csv': str(daily_csv_path),
            'preferred_daily_format': 'parquet',
            'audit_daily_format': 'csv',
            'daily_io_contract': {
                'version': 'factorforge_step3a_daily_io_contract_v1',
                'performance_path': 'parquet',
                'audit_path': 'csv',
                'csv_required_for_audit': True,
                'parquet_required_for_performance': True,
            },
        },
        step2_research_context={'smoke': True},
        mode_decision={'implementation_mode': 'operator'},
        artifact_identity={},
        operator_profile=True,
    )
    metadata = read_json(root / outputs['run_metadata_path'])
    engine_profile = ((metadata.get('performance_profile') or {}).get('formula_engine_profile') or {})
    op_profile = engine_profile.get('operator_profile') or {}
    parity_profile = engine_profile.get('parity_profile') or {}
    ok = bool(
        op_profile.get('version') == 'factorforge_operator_profile_v1'
        and op_profile.get('enabled') is True
        and int(op_profile.get('event_count') or 0) > 0
        and float(op_profile.get('unprofiled_compute_seconds') or 0.0) >= 0.0
        and parity_profile.get('enabled') is True
        and parity_profile.get('reference_seconds') is not None
        and parity_profile.get('compare_seconds') is not None
    )
    return {
        'case': 'step3b_operator_profile_metadata_present',
        'operator_profile': op_profile,
        'parity_profile': parity_profile,
        'ok': ok,
    }


def run_operator_profile_disabled_metadata_present_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP3B_OPERATOR_PROFILE_DISABLED'
    run_dir = root / 'runs' / report_id / 'step3a_local_inputs'
    run_dir.mkdir(parents=True, exist_ok=True)
    daily = build_formula_fixture_frame(unsorted=False)
    daily_csv_path = run_dir / f'daily_input__{report_id}.csv'
    daily_parquet_path = run_dir / f'daily_input__{report_id}.parquet'
    daily.to_parquet(daily_parquet_path, index=False)
    daily.to_csv(daily_csv_path, index=False)
    formula_ir = parse_formula('rank(delta(close, 1))', available_columns=list(daily.columns), raise_on_error=True)
    impl_dir = root / 'generated_code' / report_id
    impl_dir.mkdir(parents=True, exist_ok=True)
    impl = impl_dir / 'factor_impl.py'
    impl.write_text(generate_pandas_formula_code(report_id=report_id, factor_id='OPERATOR_PROFILE_DISABLED', formula_ir=formula_ir), encoding='utf-8')
    module = import_run_step3b(root)
    with temporary_env('FACTORFORGE_ENABLE_OPERATOR_PROFILE', None):
        outputs = module.generate_first_run_factor_values(
            report_id=report_id,
            factor_id='OPERATOR_PROFILE_DISABLED',
            implementation_path=impl,
            local_inputs={
                'input_mode': 'daily_only',
                'daily_df_parquet': str(daily_parquet_path),
                'daily_df_csv': str(daily_csv_path),
                'preferred_daily_format': 'parquet',
                'audit_daily_format': 'csv',
                'daily_io_contract': {
                    'version': 'factorforge_step3a_daily_io_contract_v1',
                    'performance_path': 'parquet',
                    'audit_path': 'csv',
                    'csv_required_for_audit': True,
                    'parquet_required_for_performance': True,
                },
            },
            step2_research_context={'smoke': True},
            mode_decision={'implementation_mode': 'operator'},
            artifact_identity={},
        )
    metadata = read_json(root / outputs['run_metadata_path'])
    op_profile = (((metadata.get('performance_profile') or {}).get('formula_engine_profile') or {}).get('operator_profile') or {})
    ok = bool(
        op_profile.get('version') == 'factorforge_operator_profile_v1'
        and op_profile.get('enabled') is False
    )
    return {'case': 'operator_profile_disabled_metadata_present', 'operator_profile': op_profile, 'ok': ok}


def run_step3b_polars_experimental_profile_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP3B_POLARS_EXPERIMENTAL'
    run_dir = root / 'runs' / report_id / 'step3a_local_inputs'
    run_dir.mkdir(parents=True, exist_ok=True)
    daily = build_polars_alpha017_like_frame()
    daily_csv_path = run_dir / f'daily_input__{report_id}.csv'
    daily_parquet_path = run_dir / f'daily_input__{report_id}.parquet'
    daily.to_parquet(daily_parquet_path, index=False)
    daily.to_csv(daily_csv_path, index=False)
    formula_ir = parse_formula('rank(delta(close, 1) * (volume / close))', available_columns=list(daily.columns), raise_on_error=True)
    impl_dir = root / 'generated_code' / report_id
    impl_dir.mkdir(parents=True, exist_ok=True)
    impl = impl_dir / 'factor_impl.py'
    impl.write_text(generate_pandas_formula_code(report_id=report_id, factor_id='POLARS_EXPERIMENTAL', formula_ir=formula_ir), encoding='utf-8')
    module = import_run_step3b(root)
    kwargs = {
        'report_id': report_id,
        'factor_id': 'POLARS_EXPERIMENTAL',
        'implementation_path': impl,
        'local_inputs': {
            'input_mode': 'daily_only',
            'daily_df_parquet': str(daily_parquet_path),
            'daily_df_csv': str(daily_csv_path),
            'preferred_daily_format': 'parquet',
            'audit_daily_format': 'csv',
            'daily_io_contract': {
                'version': 'factorforge_step3a_daily_io_contract_v1',
                'performance_path': 'parquet',
                'audit_path': 'csv',
                'csv_required_for_audit': True,
                'parquet_required_for_performance': True,
            },
        },
        'step2_research_context': {'smoke': True},
        'mode_decision': {'implementation_mode': 'operator'},
        'artifact_identity': {},
        'formula_engine': 'polars_experimental',
    }
    if not polars_dependency_available():
        try:
            module.generate_first_run_factor_values(**kwargs)
            token_present = False
        except SystemExit as exc:
            token_present = 'BLOCK_POLARS_EXPERIMENTAL_DEPENDENCY_MISSING' in str(exc)
        return {
            'case': 'step3b_polars_experimental_profile_present',
            'polars_installed': False,
            'rc': 1 if token_present else 0,
            'token_present': bool(token_present),
            'ok': bool(token_present),
        }

    outputs = module.generate_first_run_factor_values(**kwargs)
    metadata = read_json(root / outputs['run_metadata_path'])
    engine_profile = (metadata.get('performance_profile') or {}).get('formula_engine_profile') or {}
    ok = bool(
        engine_profile.get('engine') in {'polars_experimental', 'pandas_formula_ir_optimized'}
        and engine_profile.get('polars_enabled') is True
        and engine_profile.get('parity_checked') is True
        and int(engine_profile.get('parity_sample_rows') or 0) >= 5000
        and (
            engine_profile.get('polars_used') is True
            or (
                engine_profile.get('polars_fallback_used') is True
                and bool(engine_profile.get('polars_fallback_reason'))
            )
        )
    )
    return {
        'case': 'step3b_polars_experimental_profile_present',
        'polars_installed': True,
        'engine_profile': engine_profile,
        'ok': ok,
    }


def create_self_quant_fixture(root: Path, report_id: str) -> None:
    run_dir = root / 'runs' / report_id
    input_dir = run_dir / 'step3a_local_inputs'
    input_dir.mkdir(parents=True, exist_ok=True)
    factor_rows = []
    daily_rows = []
    for day in range(1, 10):
        for code_idx in range(1, 26):
            code = f'S{code_idx:03d}'
            trade_date = f'202001{day:02d}'
            signal = float(code_idx + day * 0.05)
            factor_rows.append({'ts_code': code, 'trade_date': trade_date, 'smoke_factor': signal})
            daily_rows.append({
                'ts_code': code,
                'trade_date': trade_date,
                'close': 10.0 + code_idx * 0.2 + day * 0.1,
                'pct_chg': float(((code_idx % 7) - 3) * 0.05 + day * 0.01),
            })
    pd.DataFrame(factor_rows).to_parquet(run_dir / f'factor_values__{report_id}.parquet', index=False)
    pd.DataFrame(factor_rows).to_csv(run_dir / f'factor_values__{report_id}.csv', index=False)
    daily = pd.DataFrame(daily_rows)
    daily.to_parquet(input_dir / f'daily_input__{report_id}.parquet', index=False)
    daily.to_csv(input_dir / f'daily_input__{report_id}.csv', index=False)
    write_json(root / 'objects' / 'factor_spec_master' / f'factor_spec_master__{report_id}.json', {'report_id': report_id, 'factor_id': 'SMOKE'})


def run_self_quant_profile_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_SELF_QUANT'
    create_self_quant_fixture(root, report_id)
    output = root / 'evaluations' / report_id / 'self_quant_analyzer' / 'evaluation_payload.json'
    proc = run_cmd([
        sys.executable,
        'skills/factor-forge-step4/scripts/self_quant_adapter.py',
        '--report-id',
        report_id,
        '--output',
        str(output),
    ], root=root)
    payload = read_json(output) if output.exists() else {}
    profile = payload.get('performance_profile') or {}
    input_io_profile = profile.get('input_io_profile') or {}
    signal_timing_contract = payload.get('signal_timing_contract') or {}
    required = {
        'load_factor_values', 'load_daily_snapshot', 'merge_forward_returns', 'ic_calculation',
        'quantile_assignment', 'long_side_evidence', 'write_tables', 'write_plots', 'total',
    }
    timing_contract_ok = (
        signal_timing_contract.get('version') == 'factorforge_signal_timing_contract_v1'
        and signal_timing_contract.get('signal_timestamp_policy') == 'close_after_market'
        and signal_timing_contract.get('label_policy') == 'next_trading_day_return'
        and signal_timing_contract.get('ic_alignment') == 'factor_value_t_vs_return_t_plus_1'
        and signal_timing_contract.get('forward_return_horizon') == 1
        and signal_timing_contract.get('forward_return_source') == 'pct_chg.shift(-1)'
        and signal_timing_contract.get('merge_keys') == ['datetime', 'code']
        and signal_timing_contract.get('same_day_return_used_as_label') is False
    )
    ok = (
        proc.returncode == 0
        and profile.get('version') == 'factorforge_self_quant_performance_profile_v1'
        and profile.get('merged_rows', 0) > 0
        and required.issubset(set((profile.get('phase_seconds') or {}).keys()))
        and input_io_profile.get('daily_selected_format') == 'parquet'
        and str(input_io_profile.get('daily_selected_path') or '').endswith('.parquet')
        and input_io_profile.get('factor_values_selected_format') == 'parquet'
        and timing_contract_ok
        and payload.get('status') == 'success'
    )
    return {
        'case': 'self_quant_performance_profile_present',
        'report_id': report_id,
        'rc': proc.returncode,
        'profile': profile,
        'input_io_profile': input_io_profile,
        'signal_timing_contract': signal_timing_contract,
        'signal_timing_contract_ok': bool(timing_contract_ok),
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': bool(ok),
    }


def run_step4_self_quant_prefers_daily_parquet_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_SELF_QUANT'
    payload_path = root / 'evaluations' / report_id / 'self_quant_analyzer' / 'evaluation_payload.json'
    payload = read_json(payload_path) if payload_path.exists() else {}
    input_io_profile = ((payload.get('performance_profile') or {}).get('input_io_profile') or {})
    ok = (
        input_io_profile.get('daily_selected_format') == 'parquet'
        and str(input_io_profile.get('daily_selected_path') or '').endswith('.parquet')
        and input_io_profile.get('factor_values_selected_format') == 'parquet'
    )
    return {'case': 'step4_self_quant_prefers_daily_parquet_when_available', 'report_id': report_id, 'input_io_profile': input_io_profile, 'ok': bool(ok)}


def run_step4_daily_csv_fallback_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_SELF_QUANT_CSV_FALLBACK'
    create_self_quant_fixture(root, report_id)
    parquet_path = root / 'runs' / report_id / 'step3a_local_inputs' / f'daily_input__{report_id}.parquet'
    if parquet_path.exists():
        parquet_path.unlink()
    output = root / 'evaluations' / report_id / 'self_quant_analyzer' / 'evaluation_payload.json'
    proc = run_cmd([
        sys.executable,
        'skills/factor-forge-step4/scripts/self_quant_adapter.py',
        '--report-id',
        report_id,
        '--output',
        str(output),
    ], root=root)
    payload = read_json(output) if output.exists() else {}
    input_io_profile = ((payload.get('performance_profile') or {}).get('input_io_profile') or {})
    ok = (
        proc.returncode == 0
        and input_io_profile.get('daily_selected_format') == 'csv'
        and str(input_io_profile.get('daily_selected_path') or '').endswith('.csv')
        and input_io_profile.get('factor_values_selected_format') == 'parquet'
    )
    return {
        'case': 'step4_daily_csv_fallback_when_parquet_missing',
        'report_id': report_id,
        'rc': proc.returncode,
        'input_io_profile': input_io_profile,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': bool(ok),
    }


def run_self_quant_parity_case(root: Path) -> dict[str, Any]:
    module = import_self_quant_adapter(root)
    rows = []
    for day in range(1, 8):
        for code_idx in range(1, 28):
            rows.append({
                'datetime': pd.Timestamp(f'2020-01-{day:02d}'),
                'trade_date': f'202001{day:02d}',
                'code': f'S{code_idx:03d}',
                'signal': float((code_idx * 7 + day) % 31),
                'future_return_1d': float(((code_idx % 9) - 4) * 0.001 + day * 0.0001),
            })
    merged = pd.DataFrame(rows)
    # Reference: exact pre-refactor assignment path used independently by quantile NAV and long-side evidence.
    working = merged[['datetime', 'trade_date', 'code', 'signal', 'future_return_1d']].copy()
    working['group_id'] = working.groupby('trade_date', sort=True)['signal'].transform(
        lambda s: module._assign_quantile_labels(s, groups=10)
    )
    expected_assigned = (
        working.dropna(subset=['group_id', 'future_return_1d'])
        .assign(group_id=lambda df: df['group_id'].astype(int))
        .sort_values(['trade_date', 'code'])
        .reset_index(drop=True)
    )
    actual_assigned = (
        module._assign_quantile_groups_once(merged, signal_col='signal', group_count=10)
        .sort_values(['trade_date', 'code'])
        .reset_index(drop=True)
    )
    assignment_equal = expected_assigned[['trade_date', 'code', 'group_id']].equals(
        actual_assigned[['trade_date', 'code', 'group_id']]
    )
    quantile_returns, quantile_nav, quantile_counts = module._build_quantile_nav_from_assigned(actual_assigned)
    ref_returns, ref_nav, ref_counts = module._build_quantile_nav(merged, signal_col='signal', group_count=10)
    returns_equal = bool(np.allclose(quantile_returns.fillna(-9999), ref_returns.fillna(-9999), atol=1e-12))
    nav_equal = bool(np.allclose(quantile_nav.fillna(-9999), ref_nav.fillna(-9999), atol=1e-12))
    counts_equal = quantile_counts.fillna(-1).equals(ref_counts.fillna(-1))
    ok = assignment_equal and returns_equal and nav_equal and counts_equal
    return {
        'case': 'self_quant_quantile_assignment_parity',
        'assignment_equal': assignment_equal,
        'quantile_returns_equal': returns_equal,
        'quantile_nav_equal': nav_equal,
        'quantile_counts_equal': counts_equal,
        'ok': bool(ok),
    }


def run_profile_script_readonly_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_SELF_QUANT'
    out = root / 'objects' / 'validation' / f'performance_profile__{report_id}.json'
    before_exists = out.exists()
    proc = run_cmd([
        sys.executable,
        'scripts/run_factorforge_performance_profile.py',
        '--report-id',
        report_id,
        '--factorforge-root',
        str(root),
    ])
    after_exists = out.exists()
    payload = json.loads(proc.stdout) if proc.returncode == 0 and proc.stdout.strip().startswith('{') else {}
    ok = (
        proc.returncode == 0
        and before_exists is False
        and after_exists is False
        and isinstance(payload.get('self_quant_performance_profile'), dict)
    )
    return {'case': 'performance_profile_script_readonly', 'rc': proc.returncode, 'wrote_report': after_exists, 'ok': bool(ok)}


def create_throughput_profile_fixture(root: Path, report_id: str, *, large_csv: bool = False, recompute_fallback: bool = False, qlib_missing_provider: bool = False) -> dict[str, Path]:
    run_dir = root / 'runs' / report_id
    eval_dir = root / 'evaluations' / report_id
    run_dir.mkdir(parents=True, exist_ok=True)
    factor_parquet = run_dir / f'factor_values__{report_id}.parquet'
    factor_csv = run_dir / f'factor_values__{report_id}.csv'
    pd.DataFrame({
        'ts_code': ['S001', 'S002', 'S001', 'S002'],
        'trade_date': ['20200101', '20200101', '20200102', '20200102'],
        'smoke_factor': [0.1, 0.2, 0.3, 0.4],
    }).to_parquet(factor_parquet, index=False)
    if large_csv:
        with factor_csv.open('wb') as handle:
            handle.truncate(101 * 1024 * 1024)
    else:
        factor_csv.write_text('ts_code,trade_date,smoke_factor\nS001,20200101,0.1\n', encoding='utf-8')
    meta = {
        'report_id': report_id,
        'row_count': 4,
        'performance_profile': {
            'version': 'factorforge_step3b_performance_profile_v1',
            'phase_seconds': {
                'read_inputs': 0.5,
                'compute_factor': 10.0,
                'normalize_sort': 9.0,
                'write_parquet': 0.4,
                'write_csv': 3.0,
                'write_metadata': 0.1,
                'total': 23.0,
            },
            'csv_output_profile': {'csv_output_policy': 'full_csv'},
        },
        'step4_factor_io_profile': {
            'version': 'factorforge_step4_factor_io_profile_v1',
            'source': 'step4_recompute_fallback' if recompute_fallback else 'step3b_factor_parquet',
            'selected_factor_format': 'computed' if recompute_fallback else 'parquet',
            'selected_factor_path': str(factor_parquet),
            'recomputed_factor': bool(recompute_fallback),
        },
        'input_io_profile': {
            'factor_values_selected_format': 'parquet',
            'daily_selected_format': 'parquet',
        },
    }
    run_meta = run_dir / f'run_metadata__{report_id}.json'
    write_json(run_meta, meta)
    self_quant_path = eval_dir / 'self_quant_analyzer' / 'evaluation_payload.json'
    write_json(self_quant_path, {
        'backend': 'self_quant_analyzer',
        'status': 'success',
        'performance_profile': {
            'phase_seconds': {'total': 4.2, 'load_factor_values': 0.2, 'load_daily_snapshot': 0.3},
            'input_io_profile': {'daily_selected_format': 'parquet', 'factor_values_selected_format': 'parquet'},
        },
    })
    qlib_path = eval_dir / 'qlib_backtest' / 'evaluation_payload.json'
    if qlib_missing_provider:
        write_json(qlib_path, {
            'backend': 'qlib_backtest',
            'status': 'failed',
            'mode': 'native',
            'summary': {'error': 'No usable qlib provider found'},
            'diagnostics': {'provider_missing': True, 'native_attempted': True},
        })
    return {
        'run_metadata': run_meta,
        'factor_parquet': factor_parquet,
        'factor_csv': factor_csv,
        'self_quant': self_quant_path,
        'qlib': qlib_path,
    }


def run_throughput_profile_reads_step3b_step4_metadata_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_THROUGHPUT_PROFILE'
    create_throughput_profile_fixture(root, report_id, qlib_missing_provider=True)
    output = root / 'throughput_profile_read.json'
    proc = run_cmd([
        sys.executable,
        'scripts/run_factorforge_throughput_profile.py',
        '--root',
        str(root),
        '--report-id',
        report_id,
        '--output',
        str(output),
    ])
    payload = read_json(output) if output.exists() else {}
    codes = {item.get('code') for item in payload.get('diagnostics', [])}
    ok = (
        proc.returncode == 0
        and payload.get('contract_version') == 'factorforge_throughput_profile_v1'
        and payload.get('artifacts_found', {}).get('step3b_run_metadata') is True
        and payload.get('artifacts_found', {}).get('step4_run_metadata') is True
        and payload.get('step3b', {}).get('compute_factor_seconds') == 10.0
        and payload.get('step4', {}).get('self_quant_seconds') == 4.2
        and 'NORMALIZE_SORT_DOMINANT' in codes
        and 'PARQUET_FORMAL_EVIDENCE_OK' in codes
        and 'QLIB_PROVIDER_MISSING_NATIVE_ATTEMPTED' in codes
    )
    return {'case': 'throughput_profile_reads_step3b_step4_metadata', 'rc': proc.returncode, 'output_exists': output.exists(), 'diagnostic_codes': sorted(codes), 'ok': bool(ok)}


def run_throughput_profile_flags_large_full_csv_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_THROUGHPUT_LARGE_CSV'
    create_throughput_profile_fixture(root, report_id, large_csv=True)
    output = root / 'throughput_profile_large_csv.json'
    proc = run_cmd([sys.executable, 'scripts/run_factorforge_throughput_profile.py', '--root', str(root), '--report-id', report_id, '--output', str(output)])
    payload = read_json(output) if output.exists() else {}
    codes = {item.get('code') for item in payload.get('diagnostics', [])}
    return {'case': 'throughput_profile_flags_large_full_csv', 'rc': proc.returncode, 'factor_csv_bytes': payload.get('step3b', {}).get('factor_csv_bytes'), 'token_present': 'FULL_CSV_LARGE' in codes, 'ok': bool(proc.returncode == 0 and 'FULL_CSV_LARGE' in codes)}


def run_throughput_profile_flags_step4_recompute_fallback_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_THROUGHPUT_RECOMPUTE'
    create_throughput_profile_fixture(root, report_id, recompute_fallback=True)
    output = root / 'throughput_profile_recompute.json'
    proc = run_cmd([sys.executable, 'scripts/run_factorforge_throughput_profile.py', '--root', str(root), '--report-id', report_id, '--output', str(output)])
    payload = read_json(output) if output.exists() else {}
    codes = {item.get('code') for item in payload.get('diagnostics', [])}
    return {'case': 'throughput_profile_flags_step4_recompute_fallback', 'rc': proc.returncode, 'token_present': 'STEP4_RECOMPUTE_FALLBACK' in codes, 'ok': bool(proc.returncode == 0 and 'STEP4_RECOMPUTE_FALLBACK' in codes)}


def run_throughput_profile_handles_missing_artifacts_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_THROUGHPUT_MISSING'
    output = root / 'throughput_profile_missing.json'
    proc = run_cmd([sys.executable, 'scripts/run_factorforge_throughput_profile.py', '--root', str(root), '--report-id', report_id, '--output', str(output)])
    payload = read_json(output) if output.exists() else {}
    codes = [item.get('code') for item in payload.get('diagnostics', [])]
    ok = proc.returncode == 0 and output.exists() and 'ARTIFACT_MISSING' in codes
    return {'case': 'throughput_profile_handles_missing_artifacts_without_crash', 'rc': proc.returncode, 'diagnostic_codes': codes, 'ok': bool(ok)}


def run_throughput_profile_blocks_non_tmp_output_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_THROUGHPUT_NON_TMP_OUTPUT'
    create_throughput_profile_fixture(root, report_id)
    output = REPO_ROOT / 'objects' / 'validation' / 'throughput_profile_non_tmp_block.json'
    if output.exists():
        output.unlink()
    proc = run_cmd([
        sys.executable,
        'scripts/run_factorforge_throughput_profile.py',
        '--root',
        str(root),
        '--report-id',
        report_id,
        '--output',
        str(output),
    ])
    token_present = 'BLOCK_THROUGHPUT_PROFILE_NON_TMP_OUTPUT' in (proc.stdout + proc.stderr)
    return {'case': 'throughput_profile_blocks_non_tmp_output_unless_explicit', 'rc': proc.returncode, 'token_present': token_present, 'output_exists': output.exists(), 'ok': bool(proc.returncode == 1 and token_present and not output.exists())}


def run_throughput_profile_reports_csv_policy_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP3B_SAMPLE_CSV'
    output = root / 'throughput_profile_csv_policy.json'
    proc = run_cmd([
        sys.executable,
        'scripts/run_factorforge_throughput_profile.py',
        '--root',
        str(root),
        '--report-id',
        report_id,
        '--output',
        str(output),
    ])
    payload = read_json(output) if output.exists() else {}
    step3b = payload.get('step3b') or {}
    codes = {item.get('code') for item in payload.get('diagnostics', [])}
    ok = (
        proc.returncode == 0
        and step3b.get('csv_output_policy') == 'sample_csv'
        and step3b.get('formal_evidence_format') == 'parquet'
        and step3b.get('parquet_formal_evidence_ok') is True
        and step3b.get('full_csv_absent_by_policy') is True
        and step3b.get('factor_csv_sample_bytes') is not None
        and 'PARQUET_FORMAL_EVIDENCE_OK' in codes
        and 'FULL_CSV_ABSENT_BY_POLICY' in codes
        and 'SAMPLE_CSV_PRESENT' in codes
    )
    return {
        'case': 'throughput_profile_reports_csv_policy',
        'report_id': report_id,
        'rc': proc.returncode,
        'step3b_csv_policy': {key: step3b.get(key) for key in [
            'csv_output_policy',
            'formal_evidence_format',
            'parquet_formal_evidence_ok',
            'full_csv_absent_by_policy',
            'factor_csv_sample_bytes',
        ]},
        'diagnostic_codes': sorted(codes),
        'ok': bool(ok),
    }


def run_throughput_profile_reports_sort_contract_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_SORT_CONTRACT_TRUSTED'
    output = root / 'throughput_profile_sort_contract.json'
    proc = run_cmd([
        sys.executable,
        'scripts/run_factorforge_throughput_profile.py',
        '--root',
        str(root),
        '--report-id',
        report_id,
        '--output',
        str(output),
    ])
    payload = read_json(output) if output.exists() else {}
    step3b = payload.get('step3b') or {}
    profile = step3b.get('normalize_sort_profile') or {}
    codes = {item.get('code') for item in payload.get('diagnostics', [])}
    ok = (
        proc.returncode == 0
        and profile.get('sort_contract_trusted') is True
        and profile.get('full_sort_skipped') is True
        and 'SORT_CONTRACT_TRUSTED' in codes
        and 'FULL_SORT_SKIPPED_BY_CONTRACT' in codes
    )
    return {
        'case': 'throughput_profile_reports_sort_contract',
        'report_id': report_id,
        'rc': proc.returncode,
        'normalize_sort_profile': profile,
        'diagnostic_codes': sorted(codes),
        'ok': bool(ok),
    }


def _run_operator_kernel_inventory(root: Path, name: str = 'operator_kernel_inventory.json') -> tuple[subprocess.CompletedProcess[str], dict[str, Any], Path]:
    output = root / name
    proc = run_cmd([
        sys.executable,
        'scripts/run_factorforge_operator_kernel_inventory.py',
        '--output',
        str(output),
    ])
    payload = read_json(output) if output.exists() else {}
    return proc, payload, output


def run_operator_kernel_inventory_contract_case(root: Path) -> dict[str, Any]:
    proc, payload, output = _run_operator_kernel_inventory(root, 'operator_kernel_inventory_contract.json')
    diagnostics = {item.get('code') for item in payload.get('diagnostics', []) if isinstance(item, dict)}
    operators = {item.get('operator') for item in payload.get('operator_inventory', []) if isinstance(item, dict)}
    required_ops = {'ts_rank', 'ts_argmin', 'ts_argmax', 'rolling_corr', 'rolling_cov'}
    ok = (
        proc.returncode == 0
        and output.exists()
        and payload.get('version') == 'factorforge_operator_kernel_inventory_v1'
        and payload.get('read_only') is True
        and ((payload.get('current_execution_model') or {}).get('step3b_factor_values_use_qlib_native') is False)
        and 'QLIB_NOT_FORMAL_OPERATOR_ENGINE' in diagnostics
        and required_ops.issubset(operators)
        and payload.get('canonical_pollution') is False
    )
    return {
        'case': 'operator_kernel_inventory_contract',
        'rc': proc.returncode,
        'output': str(output),
        'diagnostic_codes': sorted(diagnostics),
        'operators_present': sorted(required_ops & operators),
        'ok': bool(ok),
    }


def run_operator_kernel_inventory_flags_hotspots_case(root: Path) -> dict[str, Any]:
    proc, payload, output = _run_operator_kernel_inventory(root, 'operator_kernel_inventory_hotspots.json')
    by_op = {
        item.get('operator'): item
        for item in payload.get('operator_inventory', [])
        if isinstance(item, dict)
    }
    diagnostics = {item.get('code') for item in payload.get('diagnostics', []) if isinstance(item, dict)}
    default_enabled = ['ts_sum', 'ts_mean', 'ts_min', 'ts_max', 'ts_delta', 'ts_delay', 'ts_argmin', 'ts_argmax', 'rolling_corr', 'rolling_cov', 'ts_rank']
    excluded = ['ts_std']
    default_enabled_ok = all((by_op.get(op) or {}).get('default_kernel_enabled') is True for op in default_enabled)
    excluded_ok = all((by_op.get(op) or {}).get('default_kernel_enabled') is not True for op in excluded)
    ok = (
        proc.returncode == 0
        and output.exists()
        and default_enabled_ok
        and excluded_ok
        and 'OPERATOR_KERNEL_HOTSPOT_ROLLING_APPLY' in diagnostics
        and 'OPERATOR_KERNEL_HOTSPOT_GROUPBY_APPLY_CORR_COV' in diagnostics
        and 'DEFAULT_NUMPY_TS_KERNELS_ENABLED' in diagnostics
    )
    return {
        'case': 'operator_kernel_inventory_flags_hotspots',
        'rc': proc.returncode,
        'output': str(output),
        'default_kernel_enabled': {op: (by_op.get(op) or {}).get('default_kernel_enabled') for op in default_enabled},
        'default_kernel_excluded': {op: (by_op.get(op) or {}).get('default_kernel_enabled') for op in excluded},
        'diagnostic_codes': sorted(diagnostics),
        'ok': bool(ok),
    }


def run_operator_kernel_inventory_classifies_talib_case(root: Path) -> dict[str, Any]:
    proc, payload, output = _run_operator_kernel_inventory(root, 'operator_kernel_inventory_talib.json')
    diagnostics = {item.get('code') for item in payload.get('diagnostics', []) if isinstance(item, dict)}
    talib_probe = ((payload.get('optional_dependency_probe') or {}).get('talib') or {})
    landscape = {
        item.get('library'): item
        for item in payload.get('library_landscape', [])
        if isinstance(item, dict)
    }
    talib_landscape = landscape.get('TA-Lib') or {}
    ok = (
        proc.returncode == 0
        and output.exists()
        and talib_probe.get('role') == 'factor_indicator_library'
        and bool(talib_landscape)
        and 'silent_replacement_of_formula_ir_rolling_semantics' in (talib_landscape.get('not_safe_for') or [])
        and 'TA_LIB_FACTOR_LIBRARY_CANDIDATE' in diagnostics
    )
    return {
        'case': 'operator_kernel_inventory_classifies_talib_as_factor_library',
        'rc': proc.returncode,
        'output': str(output),
        'talib_probe': talib_probe,
        'talib_landscape': talib_landscape,
        'diagnostic_codes': sorted(diagnostics),
        'ok': bool(ok),
    }


def run_operator_kernel_inventory_blocks_non_tmp_output_case(root: Path) -> dict[str, Any]:
    output = REPO_ROOT / 'docs' / f'.tmp_operator_kernel_inventory_should_block_{os.getpid()}.json'
    proc = run_cmd([
        sys.executable,
        'scripts/run_factorforge_operator_kernel_inventory.py',
        '--output',
        str(output),
    ])
    combined = proc.stdout + proc.stderr
    ok = (
        proc.returncode != 0
        and 'BLOCK_OPERATOR_KERNEL_INVENTORY_NON_TMP_OUTPUT' in combined
        and not output.exists()
    )
    return {
        'case': 'operator_kernel_inventory_blocks_non_tmp_output_unless_explicit',
        'rc': proc.returncode,
        'token_present': 'BLOCK_OPERATOR_KERNEL_INVENTORY_NON_TMP_OUTPUT' in combined,
        'output_exists': output.exists(),
        'ok': bool(ok),
    }


def run_operator_kernel_inventory_no_canonical_pollution_case(root: Path) -> dict[str, Any]:
    before = snapshot_repo_files()
    proc, payload, output = _run_operator_kernel_inventory(root, 'operator_kernel_inventory_pollution.json')
    after = snapshot_repo_files()
    polluted = bool(after - before)
    ok = proc.returncode == 0 and output.exists() and payload.get('canonical_pollution') is False and not polluted
    return {
        'case': 'operator_kernel_inventory_no_canonical_pollution',
        'rc': proc.returncode,
        'output': str(output),
        'inventory_canonical_pollution': payload.get('canonical_pollution'),
        'repo_canonical_pollution': {'polluted': polluted, 'new_files': sorted(after - before)},
        'ok': bool(ok),
    }


def _run_operator_candidate_benchmark(root: Path, name: str = 'operator_candidate_benchmark.json') -> tuple[subprocess.CompletedProcess[str], dict[str, Any], Path]:
    output = root / name
    proc = run_cmd([
        sys.executable,
        'scripts/run_factorforge_operator_candidate_benchmark.py',
        '--output',
        str(output),
        '--windows',
        '5,10',
        '--ticker-count',
        '24',
        '--days',
        '60',
        '--seed',
        '707',
        '--include-ts-rank',
    ])
    payload = read_json(output) if output.exists() else {}
    return proc, payload, output


def _operator_candidate_results(payload: dict[str, Any], operators: set[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in payload.get('cases', []):
        if not isinstance(case, dict):
            continue
        for item in case.get('results', []):
            if isinstance(item, dict) and item.get('operator') in operators and item.get('candidate') != 'pandas_reference':
                results.append(item)
    return results


def run_operator_candidate_benchmark_contract_case(root: Path) -> dict[str, Any]:
    proc, payload, output = _run_operator_candidate_benchmark(root, 'operator_candidate_benchmark_contract.json')
    diagnostics = {item.get('code') for item in payload.get('diagnostics', []) if isinstance(item, dict)}
    recommendations = payload.get('recommendations') or []
    rec_safety_ok = all((rec or {}).get('safe_to_wire_into_step3b') is False for rec in recommendations if isinstance(rec, dict))
    required_diagnostics = {
        'OPERATOR_CANDIDATE_BENCHMARK_READ_ONLY',
        'PRODUCTION_OPERATOR_PATH_UNCHANGED',
        'ARGMIN_ARGMAX_CANDIDATES_BENCHMARKED',
        'CORR_COV_CANDIDATES_BENCHMARKED',
        'TS_RANK_EXISTING_CANDIDATES_INCLUDED',
    }
    ok = (
        proc.returncode == 0
        and output.exists()
        and payload.get('version') == 'factorforge_operator_candidate_benchmark_v1'
        and payload.get('read_only') is True
        and payload.get('production_semantics_changed') is False
        and payload.get('canonical_pollution') is False
        and required_diagnostics.issubset(diagnostics)
        and {'ts_argmin', 'ts_argmax', 'rolling_corr', 'rolling_cov', 'ts_rank'}.issubset(set(payload.get('operators') or []))
        and rec_safety_ok
    )
    return {
        'case': 'operator_candidate_benchmark_contract',
        'rc': proc.returncode,
        'output': str(output),
        'diagnostic_codes': sorted(diagnostics),
        'recommendations_safe_to_wire': rec_safety_ok,
        'ok': bool(ok),
    }


def run_operator_candidate_benchmark_argmin_argmax_parity_case(root: Path) -> dict[str, Any]:
    proc, payload, output = _run_operator_candidate_benchmark(root, 'operator_candidate_benchmark_argmin_argmax.json')
    results = _operator_candidate_results(payload, {'ts_argmin', 'ts_argmax'})
    parity_ok = bool(results) and all(
        item.get('status') == 'PASS'
        and item.get('parity_pass') is True
        and item.get('row_count_equal') is True
        and item.get('key_order_equal') is True
        and item.get('nan_mask_equal') is True
        and float(item.get('max_abs_diff') or 0.0) <= 1e-12
        and item.get('safe_to_wire_into_step3b') is False
        for item in results
    )
    return {
        'case': 'operator_candidate_benchmark_argmin_argmax_parity',
        'rc': proc.returncode,
        'output': str(output),
        'candidate_count': len(results),
        'parity_ok': parity_ok,
        'ok': bool(proc.returncode == 0 and parity_ok),
    }


def run_operator_candidate_benchmark_corr_cov_parity_case(root: Path) -> dict[str, Any]:
    proc, payload, output = _run_operator_candidate_benchmark(root, 'operator_candidate_benchmark_corr_cov.json')
    results: list[dict[str, Any]] = []
    for case in payload.get('cases', []):
        if not isinstance(case, dict) or str(case.get('case') or '').startswith('corr_cov_edge_'):
            continue
        for item in case.get('results', []):
            if isinstance(item, dict) and item.get('operator') in {'rolling_corr', 'rolling_cov'} and item.get('candidate') != 'pandas_reference':
                results.append(item)
    parity_ok = bool(results) and all(
        item.get('status') == 'PASS'
        and item.get('parity_pass') is True
        and item.get('row_count_equal') is True
        and item.get('key_order_equal') is True
        and item.get('nan_mask_equal') is True
        and float(item.get('max_abs_diff') or 0.0) <= 1e-10
        and item.get('safe_to_wire_into_step3b') is False
        for item in results
    )
    return {
        'case': 'operator_candidate_benchmark_corr_cov_parity',
        'rc': proc.returncode,
        'output': str(output),
        'candidate_count': len(results),
        'parity_ok': parity_ok,
        'ok': bool(proc.returncode == 0 and parity_ok),
    }


def run_operator_candidate_benchmark_corr_cov_semantic_profile_case(root: Path) -> dict[str, Any]:
    output = root / 'operator_candidate_corr_cov_semantic.json'
    proc = run_cmd([
        sys.executable,
        'scripts/run_factorforge_operator_candidate_benchmark.py',
        '--output',
        str(output),
        '--windows',
        '3,5,10',
        '--ticker-count',
        '24',
        '--days',
        '60',
        '--seed',
        '907',
    ])
    payload = read_json(output) if output.exists() else {}
    diagnostics = {item.get('code') for item in payload.get('diagnostics', []) if isinstance(item, dict)}
    profile = payload.get('corr_cov_semantic_profile') or {}
    recs = {
        item.get('operator'): item
        for item in payload.get('recommendations', [])
        if isinstance(item, dict) and item.get('operator') in {'rolling_corr', 'rolling_cov'}
    }
    ok = (
        proc.returncode == 0
        and payload.get('version') == 'factorforge_operator_candidate_benchmark_v1'
        and profile.get('version') == 'factorforge_corr_cov_semantic_profile_v1'
        and profile.get('edge_cases_included') is True
        and 'CORR_COV_EDGE_CASES_INCLUDED' in diagnostics
        and 'CORR_COV_BENCHMARK_READ_ONLY' in diagnostics
        and all((rec or {}).get('safe_to_wire_into_step3b') is False for rec in recs.values())
    )
    return {
        'case': 'operator_candidate_benchmark_corr_cov_semantic_profile',
        'rc': proc.returncode,
        'output': str(output),
        'corr_cov_semantic_profile': profile,
        'diagnostic_codes': sorted(diagnostics),
        'recommendations': recs,
        'ok': bool(ok),
    }


def run_operator_candidate_benchmark_corr_cov_edge_parity_case(root: Path) -> dict[str, Any]:
    proc, payload, output = _run_operator_candidate_benchmark(root, 'operator_candidate_benchmark_corr_cov_edge.json')
    profile = payload.get('corr_cov_semantic_profile') or {}
    recommendations = {
        item.get('operator'): item
        for item in payload.get('recommendations', [])
        if isinstance(item, dict) and item.get('operator') in {'rolling_corr', 'rolling_cov'}
    }
    edge_results = [
        item
        for case in payload.get('cases', [])
        if str((case or {}).get('case') or '').startswith('corr_cov_edge_')
        for item in (case.get('results') or [])
        if isinstance(item, dict) and item.get('operator') in {'rolling_corr', 'rolling_cov'} and item.get('candidate') != 'pandas_reference'
    ]
    parity_ok = bool(edge_results) and all(
        item.get('status') == 'PASS'
        and item.get('parity_pass') is True
        and item.get('row_count_equal') is True
        and item.get('key_order_equal') is True
        and item.get('nan_mask_equal') is True
        and item.get('allclose_pass') is True
        and float(item.get('max_abs_diff') or 0.0) <= 1e-10
        and (int(item.get('finite_count') or 0) == 0 or float(item.get('max_rel_diff') or 0.0) <= 1e-8)
        for item in edge_results
    )
    case_order_ok = all(
        (case or {}).get('candidate_matches_reference_index_order') is True
        for case in payload.get('cases', [])
        if str((case or {}).get('case') or '').startswith('corr_cov_edge_')
    )
    semantic_gate_blocks_wiring = (
        profile.get('version') == 'factorforge_corr_cov_semantic_profile_v1'
        and profile.get('edge_cases_included') is True
        and all((rec or {}).get('safe_to_wire_into_step3b') is False for rec in recommendations.values())
        and all((rec or {}).get('semantic_profile_gate_passed') is False for rec in recommendations.values())
        and profile.get('corr_safe_for_opt_in_kernel') is False
        and profile.get('cov_safe_for_opt_in_kernel') is False
    )
    edge_failures_detected = bool(edge_results) and any(item.get('parity_pass') is not True for item in edge_results)
    conservative_block_ok = bool(semantic_gate_blocks_wiring and edge_failures_detected)
    return {
        'case': 'operator_candidate_benchmark_corr_cov_edge_parity',
        'rc': proc.returncode,
        'output': str(output),
        'edge_candidate_count': len(edge_results),
        'case_order_ok': case_order_ok,
        'parity_ok': parity_ok,
        'semantic_gate_blocks_wiring': semantic_gate_blocks_wiring,
        'edge_failures_detected': edge_failures_detected,
        'corr_cov_semantic_profile': profile,
        'recommendations': recommendations,
        'ok': bool(proc.returncode == 0 and case_order_ok and (parity_ok or conservative_block_ok)),
    }


def run_operator_candidate_benchmark_blocks_non_tmp_output_case(root: Path) -> dict[str, Any]:
    output = REPO_ROOT / 'docs' / f'.tmp_operator_candidate_benchmark_should_block_{os.getpid()}.json'
    proc = run_cmd([
        sys.executable,
        'scripts/run_factorforge_operator_candidate_benchmark.py',
        '--output',
        str(output),
    ])
    combined = proc.stdout + proc.stderr
    ok = (
        proc.returncode != 0
        and 'BLOCK_OPERATOR_CANDIDATE_BENCHMARK_NON_TMP_OUTPUT' in combined
        and not output.exists()
    )
    return {
        'case': 'operator_candidate_benchmark_blocks_non_tmp_output_unless_explicit',
        'rc': proc.returncode,
        'token_present': 'BLOCK_OPERATOR_CANDIDATE_BENCHMARK_NON_TMP_OUTPUT' in combined,
        'output_exists': output.exists(),
        'ok': bool(ok),
    }


def run_operator_candidate_benchmark_corr_cov_readonly_case(root: Path) -> dict[str, Any]:
    guarded_paths = [
        REPO_ROOT / 'factor_factory' / 'formula' / 'operators.py',
        REPO_ROOT / 'factor_factory' / 'formula' / 'kernels.py',
        REPO_ROOT / 'factor_factory' / 'formula' / 'evaluator.py',
        REPO_ROOT / 'skills' / 'factor-forge-step3' / 'scripts' / 'run_step3b.py',
    ]
    before = {str(path.relative_to(REPO_ROOT)): file_sha256(path) for path in guarded_paths if path.exists()}
    proc, payload, output = _run_operator_candidate_benchmark(root, 'operator_candidate_benchmark_corr_cov_readonly.json')
    after = {str(path.relative_to(REPO_ROOT)): file_sha256(path) for path in guarded_paths if path.exists()}
    diagnostics = {item.get('code') for item in payload.get('diagnostics', []) if isinstance(item, dict)}
    ok = (
        proc.returncode == 0
        and output.exists()
        and before == after
        and 'CORR_COV_BENCHMARK_READ_ONLY' in diagnostics
        and payload.get('production_semantics_changed') is False
        and payload.get('read_only') is True
        and payload.get('canonical_pollution') is False
    )
    return {
        'case': 'operator_candidate_benchmark_corr_cov_readonly',
        'rc': proc.returncode,
        'output': str(output),
        'guarded_hashes_unchanged': before == after,
        'diagnostic_codes': sorted(diagnostics),
        'ok': bool(ok),
    }


def run_operator_candidate_benchmark_does_not_modify_formula_runtime_case(root: Path) -> dict[str, Any]:
    guarded_paths = [
        REPO_ROOT / 'factor_factory' / 'formula' / 'operators.py',
        REPO_ROOT / 'factor_factory' / 'formula' / 'kernels.py',
        REPO_ROOT / 'skills' / 'factor-forge-step3' / 'scripts' / 'run_step3b.py',
        REPO_ROOT / 'skills' / 'factor-forge-step4' / 'scripts' / 'run_step4.py',
    ]
    before = {str(path.relative_to(REPO_ROOT)): file_sha256(path) for path in guarded_paths if path.exists()}
    proc, payload, output = _run_operator_candidate_benchmark(root, 'operator_candidate_benchmark_runtime_guard.json')
    after = {str(path.relative_to(REPO_ROOT)): file_sha256(path) for path in guarded_paths if path.exists()}
    ok = (
        proc.returncode == 0
        and output.exists()
        and before == after
        and payload.get('production_semantics_changed') is False
        and payload.get('read_only') is True
        and payload.get('canonical_pollution') is False
    )
    return {
        'case': 'operator_candidate_benchmark_does_not_modify_formula_runtime',
        'rc': proc.returncode,
        'output': str(output),
        'guarded_hashes_unchanged': before == after,
        'ok': bool(ok),
    }


def create_step4_metadata_merge_fixture(root: Path, report_id: str) -> Path:
    run_dir = root / 'runs' / report_id
    input_dir = run_dir / 'step3a_local_inputs'
    input_dir.mkdir(parents=True, exist_ok=True)
    impl_dir = root / 'generated_code' / report_id
    impl_dir.mkdir(parents=True, exist_ok=True)
    objects = root / 'objects'

    rows = []
    for code_idx in range(1, 5):
        for day in range(1, 6):
            rows.append({
                'ts_code': f'S{code_idx:03d}',
                'trade_date': f'202001{day:02d}',
                'close': 10.0 + code_idx + day * 0.1,
                'pct_chg': float(code_idx * 0.01 + day * 0.001),
            })
    daily_path = input_dir / f'daily_input__{report_id}.csv'
    daily_parquet_path = input_dir / f'daily_input__{report_id}.parquet'
    daily_frame = pd.DataFrame(rows)
    daily_frame.to_parquet(daily_parquet_path, index=False)
    daily_frame.to_csv(daily_path, index=False)

    impl_path = impl_dir / 'factor_impl.py'
    impl_path.write_text(
        "def compute_factor(daily_df, minute_df=None):\n"
        "    out = daily_df[['ts_code', 'trade_date', 'close']].copy()\n"
        "    out['smoke_factor'] = out['close'].rank(pct=True)\n"
        "    return out[['ts_code', 'trade_date', 'smoke_factor']]\n",
        encoding='utf-8',
    )

    fsm = {
        'report_id': report_id,
        'factor_id': 'SMOKE',
        'canonical_spec': {'implementation_path': str(impl_path)},
        'implementation_mode_decision': {'implementation_mode': 'direct_code'},
    }
    dpm = {
        'report_id': report_id,
        'factor_id': 'SMOKE',
        'sample_window': {'start': '20200101', 'end': '20200105'},
        'field_mapping': {'ts_code': 'ts_code', 'trade_date': 'trade_date', 'close': 'close'},
        'data_sources': [{'name': 'synthetic_tmp_fixture'}],
        'local_input_paths': {
            'input_mode': 'daily_only',
            'daily_df_parquet': str(daily_parquet_path),
            'daily_df_csv': str(daily_path),
            'preferred_daily_format': 'parquet',
            'audit_daily_format': 'csv',
            'daily_io_contract': {
                'version': 'factorforge_step3a_daily_io_contract_v1',
                'performance_path': 'parquet',
                'audit_path': 'csv',
                'csv_required_for_audit': True,
                'parquet_required_for_performance': True,
            },
            'sample_window_actual': {'start': '20200101', 'end': '20200105'},
        },
    }
    handoff = {
        'report_id': report_id,
        'factor_id': 'SMOKE',
        'factor_impl_ref': str(impl_path),
        'implementation_mode_decision': {'implementation_mode': 'direct_code'},
        'local_input_paths': dpm['local_input_paths'],
        'evaluation_plan': {'backends': [{'name': 'metadata_noop', 'mode': 'noop'}], 'metric_policy': 'extensible'},
    }
    write_json(objects / 'factor_spec_master' / f'factor_spec_master__{report_id}.json', fsm)
    write_json(objects / 'data_prep_master' / f'data_prep_master__{report_id}.json', dpm)
    write_json(objects / 'handoff' / f'handoff_to_step4__{report_id}.json', handoff)

    meta_path = run_dir / f'run_metadata__{report_id}.json'
    write_json(meta_path, {
        'report_id': report_id,
        'performance_profile': {'version': 'factorforge_step3b_performance_profile_v1'},
        'output_paths': [
            f'runs/{report_id}/factor_values__{report_id}.parquet',
            f'runs/{report_id}/factor_values__{report_id}.csv',
        ],
        'run_metadata_path': f'runs/{report_id}/run_metadata__{report_id}.json',
        'producer': 'step3b',
        'boundary_note': 'step3b-owned metadata must survive Step4 overlay',
        'step2_research_context': {'source': 'synthetic'},
        'step3b_sentinel_field': {'must_survive_step4': True},
    })
    return meta_path


def run_step4_metadata_merge_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP4_METADATA_MERGE'
    meta_path = create_step4_metadata_merge_fixture(root, report_id)
    before_meta = read_json(meta_path)
    env = os.environ.copy()
    env.pop('FACTORFORGE_ROOT', None)
    env['FACTORFORGE_ALLOW_DIRECT_STEP'] = '1'
    env['FACTORFORGE_DEBUG_ROOT'] = str(root)
    proc = subprocess.run(
        [sys.executable, 'skills/factor-forge-step4/scripts/run_step4.py', '--report-id', report_id],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    after_meta = read_json(meta_path) if meta_path.exists() else {}
    input_io_profile = after_meta.get('input_io_profile') or {}
    ok = (
        proc.returncode == 0
        and after_meta.get('performance_profile') == before_meta.get('performance_profile')
        and after_meta.get('output_paths') == before_meta.get('output_paths')
        and after_meta.get('run_metadata_path') == before_meta.get('run_metadata_path')
        and after_meta.get('producer') == before_meta.get('producer')
        and after_meta.get('boundary_note') == before_meta.get('boundary_note')
        and after_meta.get('step2_research_context') == before_meta.get('step2_research_context')
        and (after_meta.get('step3b_sentinel_field') or {}).get('must_survive_step4') is True
        and after_meta.get('row_count', 0) > 0
        and after_meta.get('date_count') == 5
        and after_meta.get('ticker_count') == 4
        and after_meta.get('signal_column') == 'smoke_factor'
        and after_meta.get('run_status_candidate') == 'success'
        and input_io_profile.get('daily_selected_format') == 'parquet'
        and str(input_io_profile.get('daily_selected_path') or '').endswith('.parquet')
    )
    return {
        'case': 'step4_preserves_existing_step3b_metadata_fields',
        'report_id': report_id,
        'rc': proc.returncode,
        'metadata_path': str(meta_path),
        'preserved_keys': {
            'performance_profile': after_meta.get('performance_profile') == before_meta.get('performance_profile'),
            'output_paths': after_meta.get('output_paths') == before_meta.get('output_paths'),
            'step3b_sentinel_field': (after_meta.get('step3b_sentinel_field') or {}).get('must_survive_step4') is True,
        },
        'step4_owned_fields_updated': {
            'row_count': after_meta.get('row_count'),
            'date_count': after_meta.get('date_count'),
            'ticker_count': after_meta.get('ticker_count'),
            'signal_column': after_meta.get('signal_column'),
            'run_status_candidate': after_meta.get('run_status_candidate'),
        },
        'input_io_profile': input_io_profile,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': bool(ok),
    }


def create_step4_factor_csv_policy_fixture(root: Path, report_id: str, policy: str | None) -> dict[str, Path]:
    run_dir = root / 'runs' / report_id
    input_dir = run_dir / 'step3a_local_inputs'
    input_dir.mkdir(parents=True, exist_ok=True)
    impl_dir = root / 'generated_code' / report_id
    impl_dir.mkdir(parents=True, exist_ok=True)
    objects = root / 'objects'

    rows = []
    for code_idx in range(1, 6):
        for day in range(1, 8):
            rows.append({
                'ts_code': f'S{code_idx:03d}',
                'trade_date': f'202001{day:02d}',
                'close': 10.0 + code_idx + day * 0.1,
                'pct_chg': float(code_idx * 0.01 + day * 0.001),
            })
    daily = pd.DataFrame(rows)
    daily_csv = input_dir / f'daily_input__{report_id}.csv'
    daily_parquet = input_dir / f'daily_input__{report_id}.parquet'
    daily.to_csv(daily_csv, index=False)
    daily.to_parquet(daily_parquet, index=False)

    impl_path = impl_dir / 'factor_impl.py'
    impl_path.write_text(
        "def compute_factor(daily_df, minute_df=None):\n"
        "    out = daily_df[['ts_code', 'trade_date', 'close']].copy()\n"
        "    out['smoke_factor'] = out['close'].rank(pct=True)\n"
        "    return out[['ts_code', 'trade_date', 'smoke_factor']]\n",
        encoding='utf-8',
    )

    local_inputs = {
        'input_mode': 'daily_only',
        'daily_df_parquet': str(daily_parquet),
        'daily_df_csv': str(daily_csv),
        'preferred_daily_format': 'parquet',
        'audit_daily_format': 'csv',
        'sample_window_actual': {'start': '20200101', 'end': '20200107'},
    }
    artifact_identity = {
        'report_id': report_id,
        'factor_id': 'SMOKE',
        'source_type': 'synthetic_tmp_fixture',
        'implementation_mode': 'direct_code',
        'contract_version': 'factorforge_artifact_identity_v1',
        'producer': 'step3b',
        'upstream_producer': 'performance_smoke',
        'formula_hash': None,
        'code_hash': None,
        'code_contract_hash': 'smoke_code_contract_hash',
        'custom_block_hash': None,
        'hybrid_hash': None,
        'spec_hash': 'smoke_spec_hash',
        'branch_id': 'performance_smoke',
        'run_id': f'{report_id}__run',
        'parent_run_id': None,
        'created_at_utc': utc_now(),
        'artifact_role': 'handoff_to_step4',
    }
    write_json(objects / 'factor_spec_master' / f'factor_spec_master__{report_id}.json', {
        'report_id': report_id,
        'factor_id': 'SMOKE',
        'artifact_identity': artifact_identity,
        'canonical_spec': {'implementation_path': str(impl_path)},
        'implementation_mode_decision': {'implementation_mode': 'direct_code'},
    })
    write_json(objects / 'data_prep_master' / f'data_prep_master__{report_id}.json', {
        'report_id': report_id,
        'factor_id': 'SMOKE',
        'sample_window': {'start': '20200101', 'end': '20200107'},
        'field_mapping': {'ts_code': 'ts_code', 'trade_date': 'trade_date', 'close': 'close'},
        'data_sources': [{'name': 'synthetic_tmp_fixture'}],
        'local_input_paths': local_inputs,
    })
    write_json(objects / 'handoff' / f'handoff_to_step4__{report_id}.json', {
        'report_id': report_id,
        'factor_id': 'SMOKE',
        'artifact_identity': artifact_identity,
        'factor_impl_ref': str(impl_path),
        'implementation_mode_decision': {'implementation_mode': 'direct_code'},
        'local_input_paths': local_inputs,
        'evaluation_plan': {'backends': [{'name': 'self_quant_analyzer', 'mode': 'quick'}], 'metric_policy': 'extensible'},
    })

    factor_parquet = run_dir / f'factor_values__{report_id}.parquet'
    factor_csv = run_dir / f'factor_values__{report_id}.csv'
    factor_sample = run_dir / f'factor_values_sample__{report_id}.csv'
    run_meta = run_dir / f'run_metadata__{report_id}.json'
    meta: dict[str, Any] = {
        'report_id': report_id,
        'producer': 'step3b',
        'performance_profile': {'version': 'factorforge_step3b_performance_profile_v1'},
    }
    if policy is not None:
        meta['performance_profile']['csv_output_profile'] = {
            'version': 'factorforge_csv_output_profile_v1',
            'formal_evidence_format': 'parquet',
            'csv_output_policy': policy,
            'parquet_rows_written': len(daily),
            'csv_rows_written': 0,
            'csv_sample_strategy': 'none',
            'full_csv_available': False,
            'factor_parquet_path': str(factor_parquet),
            'factor_csv_path': None,
            'factor_sample_csv_path': None,
            'sample_schema_parity': None,
            'full_csv_absent_validated': policy in {'sample_csv', 'no_csv'},
            'full_csv_absence_reason': f'step3b_{policy}_policy' if policy in {'sample_csv', 'no_csv'} else None,
            'csv_path': None,
            'csv_sample_path': None,
        }
    if policy == 'sample_csv':
        factor_sample.write_text('ts_code,trade_date,smoke_factor\nS001,20200101,0.1\n', encoding='utf-8')
        meta['performance_profile']['csv_output_profile'].update({
            'csv_rows_written': 1,
            'csv_sample_strategy': 'head_tail',
            'factor_sample_csv_path': str(factor_sample),
            'sample_schema_parity': True,
            'csv_sample_path': str(factor_sample),
        })
    write_json(run_meta, meta)
    return {
        'run_dir': run_dir,
        'factor_parquet': factor_parquet,
        'factor_csv': factor_csv,
        'factor_sample': factor_sample,
        'run_meta': run_meta,
    }


def run_step4_direct(root: Path, report_id: str, *, extra_args: list[str] | None = None, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop('FACTORFORGE_ROOT', None)
    env['FACTORFORGE_ALLOW_DIRECT_STEP'] = '1'
    env['FACTORFORGE_DEBUG_ROOT'] = str(root)
    if extra_env:
        env.update({str(k): str(v) for k, v in extra_env.items()})
    return subprocess.run(
        [sys.executable, 'skills/factor-forge-step4/scripts/run_step4.py', '--report-id', report_id, *(extra_args or [])],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


def run_step4_respects_step3b_sample_csv_policy_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP4_SAMPLE_CSV_POLICY'
    paths = create_step4_factor_csv_policy_fixture(root, report_id, 'sample_csv')
    before_sample = paths['factor_sample'].read_bytes()
    before_mtime = paths['factor_sample'].stat().st_mtime_ns
    before_full_exists = paths['factor_csv'].exists()
    proc = run_step4_direct(root, report_id)
    after_meta = read_json(paths['run_meta']) if paths['run_meta'].exists() else {}
    observed = after_meta.get('step4_factor_csv_policy_observed') or {}
    payload_path = root / 'evaluations' / report_id / 'self_quant_analyzer' / 'evaluation_payload.json'
    payload = read_json(payload_path) if payload_path.exists() else {}
    input_io_profile = ((payload.get('performance_profile') or {}).get('input_io_profile') or {})
    ok = (
        proc.returncode == 0
        and before_full_exists is False
        and not paths['factor_csv'].exists()
        and paths['factor_sample'].exists()
        and paths['factor_sample'].read_bytes() == before_sample
        and paths['factor_sample'].stat().st_mtime_ns == before_mtime
        and observed.get('csv_output_policy') == 'sample_csv'
        and observed.get('factor_csv_written_by_step4') is False
        and observed.get('factor_csv_write_skipped_reason') == 'step3b_sample_csv_policy'
        and input_io_profile.get('factor_values_selected_format') == 'parquet'
    )
    return {
        'case': 'step4_respects_step3b_sample_csv_policy',
        'report_id': report_id,
        'rc': proc.returncode,
        'full_csv_exists': paths['factor_csv'].exists(),
        'sample_csv_exists': paths['factor_sample'].exists(),
        'sample_mtime_unchanged': paths['factor_sample'].exists() and paths['factor_sample'].stat().st_mtime_ns == before_mtime,
        'step4_factor_csv_policy_observed': observed,
        'self_quant_input_io_profile': input_io_profile,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': bool(ok),
    }


def run_step4_reuses_step3b_factor_parquet_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP4_REUSES_STEP3B_FACTOR_PARQUET'
    paths = create_step4_factor_csv_policy_fixture(root, report_id, 'sample_csv')
    factor_df = pd.DataFrame([
        {'ts_code': 'S001', 'trade_date': '20200101', 'smoke_factor': 0.2},
        {'ts_code': 'S002', 'trade_date': '20200101', 'smoke_factor': 0.8},
        {'ts_code': 'S001', 'trade_date': '20200102', 'smoke_factor': 0.4},
        {'ts_code': 'S002', 'trade_date': '20200102', 'smoke_factor': 0.6},
        {'ts_code': 'S001', 'trade_date': '20200103', 'smoke_factor': 0.3},
        {'ts_code': 'S002', 'trade_date': '20200103', 'smoke_factor': 0.7},
    ])
    factor_df.to_parquet(paths['factor_parquet'], index=False)
    impl_path = root / 'generated_code' / report_id / 'factor_impl.py'
    impl_path.write_text(
        "def compute_factor(daily_df, minute_df=None):\n"
        "    raise RuntimeError('BLOCK_STEP4_RECOMPUTED_FACTOR')\n",
        encoding='utf-8',
    )
    before_parquet_mtime = paths['factor_parquet'].stat().st_mtime_ns
    proc = run_step4_direct(root, report_id)
    after_meta = read_json(paths['run_meta']) if paths['run_meta'].exists() else {}
    factor_io_profile = after_meta.get('step4_factor_io_profile') or {}
    payload_path = root / 'evaluations' / report_id / 'self_quant_analyzer' / 'evaluation_payload.json'
    payload = read_json(payload_path) if payload_path.exists() else {}
    input_io_profile = ((payload.get('performance_profile') or {}).get('input_io_profile') or {})
    ok = (
        proc.returncode == 0
        and paths['factor_parquet'].exists()
        and paths['factor_parquet'].stat().st_mtime_ns == before_parquet_mtime
        and factor_io_profile.get('source') == 'step3b_factor_parquet'
        and factor_io_profile.get('recomputed_factor') is False
        and after_meta.get('row_count') == len(factor_df)
        and input_io_profile.get('factor_values_selected_format') == 'parquet'
    )
    return {
        'case': 'step4_reuses_step3b_factor_parquet_without_recompute',
        'report_id': report_id,
        'rc': proc.returncode,
        'factor_parquet_mtime_unchanged': paths['factor_parquet'].exists() and paths['factor_parquet'].stat().st_mtime_ns == before_parquet_mtime,
        'step4_factor_io_profile': factor_io_profile,
        'row_count': after_meta.get('row_count'),
        'self_quant_input_io_profile': input_io_profile,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': bool(ok),
    }


def run_step4_preserves_prior_step4_parquet_provenance_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP4_PRIOR_STEP4_PARQUET_PROVENANCE'
    paths = create_step4_factor_csv_policy_fixture(root, report_id, None)
    factor_df = pd.DataFrame([
        {'ts_code': 'S001', 'trade_date': '20200101', 'smoke_factor': 0.25},
        {'ts_code': 'S002', 'trade_date': '20200101', 'smoke_factor': 0.75},
        {'ts_code': 'S001', 'trade_date': '20200102', 'smoke_factor': 0.35},
        {'ts_code': 'S002', 'trade_date': '20200102', 'smoke_factor': 0.65},
    ])
    factor_df.to_parquet(paths['factor_parquet'], index=False)
    write_json(paths['run_meta'], {
        'report_id': report_id,
        'producer': 'step4',
        'step4_factor_io_profile': {
            'version': 'factorforge_step4_factor_io_profile_v1',
            'source': 'step4_recompute_fallback',
            'recomputed_factor': True,
            'parquet_written_by_step4': True,
        },
    })
    impl_path = root / 'generated_code' / report_id / 'factor_impl.py'
    impl_path.write_text(
        "def compute_factor(daily_df, minute_df=None):\n"
        "    raise RuntimeError('BLOCK_STEP4_RECOMPUTED_FACTOR')\n",
        encoding='utf-8',
    )
    before_parquet_mtime = paths['factor_parquet'].stat().st_mtime_ns
    proc = run_step4_direct(root, report_id)
    after_meta = read_json(paths['run_meta']) if paths['run_meta'].exists() else {}
    factor_io_profile = after_meta.get('step4_factor_io_profile') or {}
    ok = (
        proc.returncode == 0
        and paths['factor_parquet'].exists()
        and paths['factor_parquet'].stat().st_mtime_ns == before_parquet_mtime
        and factor_io_profile.get('source') == 'prior_step4_parquet'
        and factor_io_profile.get('recomputed_factor') is False
        and factor_io_profile.get('upstream_recomputed_factor') is True
        and after_meta.get('row_count') == len(factor_df)
    )
    return {
        'case': 'step4_preserves_prior_step4_parquet_provenance',
        'report_id': report_id,
        'rc': proc.returncode,
        'factor_parquet_mtime_unchanged': paths['factor_parquet'].exists() and paths['factor_parquet'].stat().st_mtime_ns == before_parquet_mtime,
        'step4_factor_io_profile': factor_io_profile,
        'row_count': after_meta.get('row_count'),
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': bool(ok),
    }


def run_step4_respects_step3b_no_csv_policy_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP4_NO_CSV_POLICY'
    paths = create_step4_factor_csv_policy_fixture(root, report_id, 'no_csv')
    proc = run_step4_direct(root, report_id)
    after_meta = read_json(paths['run_meta']) if paths['run_meta'].exists() else {}
    observed = after_meta.get('step4_factor_csv_policy_observed') or {}
    ok = (
        proc.returncode == 0
        and not paths['factor_csv'].exists()
        and not paths['factor_sample'].exists()
        and observed.get('csv_output_policy') == 'no_csv'
        and observed.get('factor_csv_written_by_step4') is False
        and observed.get('factor_csv_write_skipped_reason') == 'step3b_no_csv_policy'
    )
    return {
        'case': 'step4_respects_step3b_no_csv_policy',
        'report_id': report_id,
        'rc': proc.returncode,
        'full_csv_exists': paths['factor_csv'].exists(),
        'sample_csv_exists': paths['factor_sample'].exists(),
        'step4_factor_csv_policy_observed': observed,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': bool(ok),
    }


def run_step4_legacy_missing_csv_policy_full_csv_compat_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP4_LEGACY_CSV_POLICY'
    paths = create_step4_factor_csv_policy_fixture(root, report_id, None)
    proc = run_step4_direct(root, report_id)
    after_meta = read_json(paths['run_meta']) if paths['run_meta'].exists() else {}
    observed = after_meta.get('step4_factor_csv_policy_observed') or {}
    ok = (
        proc.returncode == 0
        and paths['factor_csv'].exists()
        and observed.get('csv_output_policy') == 'legacy_missing'
        and observed.get('factor_csv_written_by_step4') is True
    )
    return {
        'case': 'step4_legacy_missing_csv_policy_full_csv_compat',
        'report_id': report_id,
        'rc': proc.returncode,
        'full_csv_exists': paths['factor_csv'].exists(),
        'step4_factor_csv_policy_observed': observed,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': bool(ok),
    }


def run_step4_invalid_factor_csv_policy_blocks_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP4_INVALID_CSV_POLICY'
    _paths = create_step4_factor_csv_policy_fixture(root, report_id, 'bad_policy')
    proc = run_step4_direct(root, report_id)
    output = proc.stdout + proc.stderr
    token_present = 'BLOCK_STEP4_INVALID_FACTOR_CSV_POLICY' in output
    return {
        'case': 'step4_invalid_factor_csv_policy_blocks',
        'report_id': report_id,
        'rc': proc.returncode,
        'token_present': token_present,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': bool(proc.returncode == 1 and token_present),
    }


def ensure_step4_no_csv_parquet_fixture(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP4_NO_CSV_PARQUET_FORMAL'
    paths = create_step4_factor_csv_policy_fixture(root, report_id, 'no_csv')
    input_dir = root / 'runs' / report_id / 'step3a_local_inputs'
    rows = []
    for code_idx in range(1, 25):
        for day in range(1, 8):
            rows.append({
                'ts_code': f'S{code_idx:03d}',
                'trade_date': f'202001{day:02d}',
                'close': 10.0 + code_idx + day * 0.1,
                'pct_chg': float(code_idx * 0.001 + day * 0.0005),
            })
    daily = pd.DataFrame(rows)
    daily.to_csv(input_dir / f'daily_input__{report_id}.csv', index=False)
    daily.to_parquet(input_dir / f'daily_input__{report_id}.parquet', index=False)
    handoff_path = root / 'objects' / 'handoff' / f'handoff_to_step4__{report_id}.json'
    handoff = read_json(handoff_path)
    handoff['evaluation_plan'] = {
        'backends': [{'name': 'self_quant_analyzer', 'mode': 'quick'}],
        'metric_policy': 'extensible',
    }
    write_json(handoff_path, handoff)
    proc = run_step4_direct(root, report_id)
    meta = read_json(paths['run_meta']) if paths['run_meta'].exists() else {}
    payload_path = root / 'evaluations' / report_id / 'self_quant_analyzer' / 'evaluation_payload.json'
    payload = read_json(payload_path) if payload_path.exists() else {}
    return {
        'report_id': report_id,
        'paths': paths,
        'proc': proc,
        'run_metadata': meta,
        'self_quant_payload': payload,
    }


def run_step4_uses_parquet_when_full_csv_absent_case(root: Path) -> dict[str, Any]:
    ctx = ensure_step4_no_csv_parquet_fixture(root)
    paths = ctx['paths']
    payload = ctx['self_quant_payload']
    input_io = ((payload.get('performance_profile') or {}).get('input_io_profile') or {})
    observed = ctx['run_metadata'].get('step4_factor_csv_policy_observed') or {}
    ok = (
        ctx['proc'].returncode == 0
        and paths['factor_parquet'].exists()
        and not paths['factor_csv'].exists()
        and not paths['factor_sample'].exists()
        and input_io.get('factor_values_selected_format') == 'parquet'
        and observed.get('csv_output_policy') == 'no_csv'
        and observed.get('factor_csv_written_by_step4') is False
    )
    return {
        'case': 'step4_uses_parquet_when_full_csv_absent',
        'report_id': ctx['report_id'],
        'rc': ctx['proc'].returncode,
        'factor_parquet_exists': paths['factor_parquet'].exists(),
        'factor_csv_exists': paths['factor_csv'].exists(),
        'factor_sample_exists': paths['factor_sample'].exists(),
        'self_quant_input_io_profile': input_io,
        'step4_factor_csv_policy_observed': observed,
        'stdout_tail': tail(ctx['proc'].stdout),
        'stderr_tail': tail(ctx['proc'].stderr),
        'ok': bool(ok),
    }


def run_validate_step4_accepts_no_csv_with_parquet_case(root: Path) -> dict[str, Any]:
    ctx = ensure_step4_no_csv_parquet_fixture(root)
    proc = run_cmd([
        sys.executable,
        'skills/factor-forge-step4/scripts/validate_step4.py',
        '--report-id',
        ctx['report_id'],
    ], root=root)
    output = proc.stdout + proc.stderr
    return {
        'case': 'validate_step4_accepts_no_csv_with_parquet',
        'report_id': ctx['report_id'],
        'step4_rc': ctx['proc'].returncode,
        'validate_rc': proc.returncode,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': bool(ctx['proc'].returncode == 0 and proc.returncode == 0 and 'RESULT: PASS' in output),
    }


def ensure_step4_qlib_preflight_fixture(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP4_QLIB_PREFLIGHT'
    paths = create_step4_factor_csv_policy_fixture(root, report_id, 'sample_csv')
    input_dir = root / 'runs' / report_id / 'step3a_local_inputs'
    rows = []
    for code_idx in range(1, 25):
        for day in range(1, 8):
            rows.append({
                'ts_code': f'S{code_idx:03d}',
                'trade_date': f'202001{day:02d}',
                'close': 10.0 + code_idx + day * 0.1,
                'pct_chg': float(code_idx * 0.001 + day * 0.0005),
            })
    daily = pd.DataFrame(rows)
    daily.to_csv(input_dir / f'daily_input__{report_id}.csv', index=False)
    daily.to_parquet(input_dir / f'daily_input__{report_id}.parquet', index=False)
    handoff_path = root / 'objects' / 'handoff' / f'handoff_to_step4__{report_id}.json'
    handoff = read_json(handoff_path)
    handoff['evaluation_plan'] = {
        'backends': [
            {'name': 'self_quant_analyzer', 'mode': 'quick'},
            {
                'name': 'qlib_backtest',
                'mode': 'native',
                'provider_uri': str(root / 'missing_qlib_provider'),
            },
        ],
        'metric_policy': 'extensible',
    }
    write_json(handoff_path, handoff)
    meta_path = paths['run_meta']
    if not (meta_path.exists() and (read_json(meta_path).get('backend_timing_profile') or {}).get('version') == 'factorforge_step4_backend_timing_profile_v1'):
        proc = run_step4_direct(root, report_id)
    else:
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')
    factor_run_master_path = root / 'objects' / 'factor_run_master' / f'factor_run_master__{report_id}.json'
    qlib_payload_path = root / 'evaluations' / report_id / 'qlib_backtest' / 'evaluation_payload.json'
    self_quant_payload_path = root / 'evaluations' / report_id / 'self_quant_analyzer' / 'evaluation_payload.json'
    return {
        'report_id': report_id,
        'paths': paths,
        'proc': proc,
        'run_metadata': read_json(meta_path) if meta_path.exists() else {},
        'factor_run_master': read_json(factor_run_master_path) if factor_run_master_path.exists() else {},
        'qlib_payload': read_json(qlib_payload_path) if qlib_payload_path.exists() else {},
        'self_quant_payload': read_json(self_quant_payload_path) if self_quant_payload_path.exists() else {},
        'qlib_payload_path': qlib_payload_path,
        'self_quant_payload_path': self_quant_payload_path,
    }


def run_step4_qlib_preflight_skips_missing_provider_case(root: Path) -> dict[str, Any]:
    ctx = ensure_step4_qlib_preflight_fixture(root)
    proc = ctx['proc']
    qlib_payload = ctx['qlib_payload']
    preflight = qlib_payload.get('qlib_preflight') or {}
    ok = (
        proc.returncode == 0
        and qlib_payload.get('status') == 'skipped'
        and preflight.get('provider_uri_checked') is True
        and preflight.get('provider_present') is False
        and preflight.get('native_attempted') is False
        and preflight.get('status') == 'skipped_native_missing_provider'
    )
    return {
        'case': 'step4_qlib_preflight_skips_missing_provider',
        'report_id': ctx['report_id'],
        'rc': proc.returncode,
        'qlib_status': qlib_payload.get('status'),
        'qlib_preflight': preflight,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': bool(ok),
    }


def run_step4_backend_timing_profile_records_self_quant_case(root: Path) -> dict[str, Any]:
    ctx = ensure_step4_qlib_preflight_fixture(root)
    timing = ctx['run_metadata'].get('backend_timing_profile') or {}
    self_quant = ((timing.get('backends') or {}).get('self_quant_analyzer') or {})
    ok = (
        ctx['proc'].returncode == 0
        and timing.get('version') == 'factorforge_step4_backend_timing_profile_v1'
        and self_quant.get('attempted') is True
        and self_quant.get('status') in {'success', 'partial'}
        and isinstance(self_quant.get('wall_seconds'), (int, float))
    )
    return {
        'case': 'step4_backend_timing_profile_records_self_quant',
        'report_id': ctx['report_id'],
        'rc': ctx['proc'].returncode,
        'self_quant_timing': self_quant,
        'ok': bool(ok),
    }


def run_step4_backend_timing_profile_records_qlib_skipped_case(root: Path) -> dict[str, Any]:
    ctx = ensure_step4_qlib_preflight_fixture(root)
    timing = ctx['run_metadata'].get('backend_timing_profile') or {}
    qlib = ((timing.get('backends') or {}).get('qlib_native') or {})
    ok = (
        ctx['proc'].returncode == 0
        and timing.get('version') == 'factorforge_step4_backend_timing_profile_v1'
        and qlib.get('attempted') is False
        and qlib.get('status') == 'skipped_native_missing_provider'
        and isinstance(qlib.get('preflight_seconds'), (int, float))
    )
    return {
        'case': 'step4_backend_timing_profile_records_qlib_skipped',
        'report_id': ctx['report_id'],
        'rc': ctx['proc'].returncode,
        'qlib_timing': qlib,
        'ok': bool(ok),
    }


def run_step4_missing_qlib_provider_not_marked_success_case(root: Path) -> dict[str, Any]:
    ctx = ensure_step4_qlib_preflight_fixture(root)
    qlib_payload = ctx['qlib_payload']
    backend_runs = (((ctx['factor_run_master'].get('evaluation_results') or {}).get('backend_runs')) or [])
    qlib_run = next((item for item in backend_runs if item.get('backend') == 'qlib_backtest'), {})
    ok = (
        ctx['proc'].returncode == 0
        and qlib_payload.get('status') == 'skipped'
        and qlib_run.get('status') == 'skipped'
        and qlib_payload.get('status') != 'success'
        and qlib_run.get('status') != 'success'
    )
    return {
        'case': 'step4_missing_qlib_provider_not_marked_success',
        'report_id': ctx['report_id'],
        'rc': ctx['proc'].returncode,
        'payload_status': qlib_payload.get('status'),
        'backend_run_status': qlib_run.get('status'),
        'ok': bool(ok),
    }


def run_step4_shared_evaluation_context_default_path_unchanged_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP4_SHARED_CONTEXT_DEFAULT'
    paths = create_step4_factor_csv_policy_fixture(root, report_id, 'sample_csv')
    proc = run_step4_direct(root, report_id)
    meta = read_json(paths['run_meta']) if paths['run_meta'].exists() else {}
    payload_path = root / 'evaluations' / report_id / 'self_quant_analyzer' / 'evaluation_payload.json'
    payload = read_json(payload_path) if payload_path.exists() else {}
    shared_meta = meta.get('shared_evaluation_context') or {}
    shared_sq = ((payload.get('performance_profile') or {}).get('shared_evaluation_context') or {})
    context_path = paths['run_dir'] / f'shared_evaluation_context__{report_id}.json'
    ok = (
        proc.returncode == 0
        and context_path.exists() is False
        and shared_meta.get('enabled') is False
        and shared_sq.get('used') is not True
    )
    return {
        'case': 'step4_shared_evaluation_context_default_path_unchanged',
        'report_id': report_id,
        'rc': proc.returncode,
        'context_exists': context_path.exists(),
        'shared_context_metadata': shared_meta,
        'self_quant_shared_context': shared_sq,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': bool(ok),
    }


def run_step4_builds_shared_evaluation_context_opt_in_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_STEP4_SHARED_CONTEXT_BUILD'
    paths = create_step4_factor_csv_policy_fixture(root, report_id, 'sample_csv')
    proc = run_step4_direct(root, report_id, extra_args=['--enable-shared-evaluation-context'])
    meta = read_json(paths['run_meta']) if paths['run_meta'].exists() else {}
    shared_meta = meta.get('shared_evaluation_context') or {}
    context_path = paths['run_dir'] / f'shared_evaluation_context__{report_id}.json'
    context = read_json(context_path) if context_path.exists() else {}
    context_paths = context.get('paths') or {}
    row_counts = context.get('row_counts') or {}
    required_paths_exist = all(
        Path(str(context_paths.get(key) or '')).exists()
        for key in ['factor_signal_parquet', 'daily_forward_returns_parquet', 'merged_signal_return_parquet']
    )
    ok = (
        proc.returncode == 0
        and context.get('version') == 'factorforge_shared_evaluation_context_v1'
        and shared_meta.get('enabled') is True
        and shared_meta.get('built') is True
        and required_paths_exist
        and int(row_counts.get('factor_signal') or 0) > 0
        and int(row_counts.get('daily_forward_returns') or 0) > 0
        and int(row_counts.get('merged_signal_return') or 0) > 0
        and bool(context.get('factor_values_hash'))
        and bool(context.get('daily_input_hash'))
    )
    return {
        'case': 'step4_builds_shared_evaluation_context_opt_in',
        'report_id': report_id,
        'rc': proc.returncode,
        'context_path': str(context_path),
        'context_paths_exist': required_paths_exist,
        'row_counts': row_counts,
        'shared_context_metadata': shared_meta,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': bool(ok),
    }


def run_self_quant_uses_shared_evaluation_context_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_SELF_QUANT_SHARED_CONTEXT_USED'
    paths = create_step4_factor_csv_policy_fixture(root, report_id, 'sample_csv')
    proc = run_step4_direct(root, report_id, extra_args=['--enable-shared-evaluation-context'])
    payload_path = root / 'evaluations' / report_id / 'self_quant_analyzer' / 'evaluation_payload.json'
    payload = read_json(payload_path) if payload_path.exists() else {}
    shared_sq = ((payload.get('performance_profile') or {}).get('shared_evaluation_context') or {})
    timing = (read_json(paths['run_meta']).get('backend_timing_profile') or {}) if paths['run_meta'].exists() else {}
    ok = (
        proc.returncode == 0
        and shared_sq.get('available') is True
        and shared_sq.get('used') is True
        and shared_sq.get('identity_validated') is True
        and shared_sq.get('source') == 'merged_signal_return_parquet'
        and ((timing.get('shared_evaluation_context') or {}).get('built') is True)
    )
    return {
        'case': 'self_quant_uses_shared_evaluation_context',
        'report_id': report_id,
        'rc': proc.returncode,
        'self_quant_shared_context': shared_sq,
        'backend_timing_profile': timing,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': bool(ok),
    }


def _metric_close(a: Any, b: Any, tol: float = 1e-12) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return a == b


def run_self_quant_shared_context_parity_with_legacy_path_case(root: Path) -> dict[str, Any]:
    legacy_id = 'PERF_SMOKE_SELF_QUANT_SHARED_PARITY_LEGACY'
    shared_id = 'PERF_SMOKE_SELF_QUANT_SHARED_PARITY_SHARED'
    create_step4_factor_csv_policy_fixture(root, legacy_id, 'sample_csv')
    create_step4_factor_csv_policy_fixture(root, shared_id, 'sample_csv')
    legacy_proc = run_step4_direct(root, legacy_id)
    shared_proc = run_step4_direct(root, shared_id, extra_args=['--enable-shared-evaluation-context'])
    legacy_payload = read_json(root / 'evaluations' / legacy_id / 'self_quant_analyzer' / 'evaluation_payload.json')
    shared_payload = read_json(root / 'evaluations' / shared_id / 'self_quant_analyzer' / 'evaluation_payload.json')
    parity_fields = {
        'rank_ic_mean': _metric_close((legacy_payload.get('ic_summary') or {}).get('rank_ic_mean'), (shared_payload.get('ic_summary') or {}).get('rank_ic_mean')),
        'pearson_ic_mean': _metric_close((legacy_payload.get('ic_summary') or {}).get('pearson_ic_mean'), (shared_payload.get('ic_summary') or {}).get('pearson_ic_mean')),
        'long_side_sharpe': _metric_close((legacy_payload.get('long_side_performance') or {}).get('long_side_sharpe'), (shared_payload.get('long_side_performance') or {}).get('long_side_sharpe')),
        'merged_rows': (legacy_payload.get('coverage') or {}).get('merged_rows') == (shared_payload.get('coverage') or {}).get('merged_rows'),
        'date_count': (legacy_payload.get('coverage') or {}).get('date_count') == (shared_payload.get('coverage') or {}).get('date_count'),
        'ticker_count': (legacy_payload.get('coverage') or {}).get('ticker_count') == (shared_payload.get('coverage') or {}).get('ticker_count'),
    }
    shared_sq = ((shared_payload.get('performance_profile') or {}).get('shared_evaluation_context') or {})
    ok = legacy_proc.returncode == 0 and shared_proc.returncode == 0 and shared_sq.get('used') is True and all(parity_fields.values())
    return {
        'case': 'self_quant_shared_context_parity_with_legacy_path',
        'legacy_report_id': legacy_id,
        'shared_report_id': shared_id,
        'legacy_rc': legacy_proc.returncode,
        'shared_rc': shared_proc.returncode,
        'parity_fields': parity_fields,
        'self_quant_shared_context': shared_sq,
        'ok': bool(ok),
    }


def run_shared_evaluation_context_rejected_on_identity_mismatch_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_SHARED_CONTEXT_IDENTITY_MISMATCH'
    paths = create_step4_factor_csv_policy_fixture(root, report_id, 'sample_csv')
    proc = run_step4_direct(root, report_id, extra_args=['--enable-shared-evaluation-context'])
    context_path = paths['run_dir'] / f'shared_evaluation_context__{report_id}.json'
    context = read_json(context_path) if context_path.exists() else {}
    context['factor_values_hash'] = 'bad_hash_for_smoke'
    write_json(context_path, context)
    output_path = root / 'evaluations' / report_id / 'self_quant_analyzer' / 'evaluation_payload_identity_mismatch.json'
    env = os.environ.copy()
    env['FACTORFORGE_ROOT'] = str(root)
    env['FACTORFORGE_SHARED_EVALUATION_CONTEXT_PATH'] = str(context_path)
    sq_proc = subprocess.run(
        [sys.executable, 'skills/factor-forge-step4/scripts/self_quant_adapter.py', '--report-id', report_id, '--output', str(output_path)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    payload = read_json(output_path) if output_path.exists() else {}
    shared_sq = ((payload.get('performance_profile') or {}).get('shared_evaluation_context') or {})
    ok = (
        proc.returncode == 0
        and sq_proc.returncode == 0
        and shared_sq.get('available') is True
        and shared_sq.get('used') is False
        and shared_sq.get('fallback_reason') == 'factor_values_hash_mismatch'
    )
    return {
        'case': 'shared_evaluation_context_rejected_on_identity_mismatch',
        'report_id': report_id,
        'step4_rc': proc.returncode,
        'self_quant_rc': sq_proc.returncode,
        'self_quant_shared_context': shared_sq,
        'stdout_tail': tail(sq_proc.stdout),
        'stderr_tail': tail(sq_proc.stderr),
        'ok': bool(ok),
    }


def run_shared_evaluation_context_rejects_tampered_merged_artifact_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_SHARED_CONTEXT_TAMPERED_MERGED'
    paths = create_step4_factor_csv_policy_fixture(root, report_id, 'sample_csv')
    proc = run_step4_direct(root, report_id, extra_args=['--enable-shared-evaluation-context'])
    context_path = paths['run_dir'] / f'shared_evaluation_context__{report_id}.json'
    context = read_json(context_path) if context_path.exists() else {}
    merged_original = Path((context.get('paths') or {}).get('merged_signal_return_parquet') or '')
    tampered_path = paths['run_dir'] / f'merged_signal_return_tampered__{report_id}.parquet'
    if merged_original.exists():
        tampered = pd.read_parquet(merged_original)
        if 'future_return_1d' in tampered.columns:
            tampered['future_return_1d'] = 999.0
        tampered.to_parquet(tampered_path, index=False)
    context.setdefault('paths', {})['merged_signal_return_parquet'] = str(tampered_path)
    write_json(context_path, context)
    output_path = root / 'evaluations' / report_id / 'self_quant_analyzer' / 'evaluation_payload_tampered_merged.json'
    env = os.environ.copy()
    env['FACTORFORGE_ROOT'] = str(root)
    env['FACTORFORGE_SHARED_EVALUATION_CONTEXT_PATH'] = str(context_path)
    sq_proc = subprocess.run(
        [sys.executable, 'skills/factor-forge-step4/scripts/self_quant_adapter.py', '--report-id', report_id, '--output', str(output_path)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    payload = read_json(output_path) if output_path.exists() else {}
    shared_sq = ((payload.get('performance_profile') or {}).get('shared_evaluation_context') or {})
    ok = (
        proc.returncode == 0
        and sq_proc.returncode == 0
        and shared_sq.get('available') is True
        and shared_sq.get('used') is False
        and shared_sq.get('fallback_reason') in {
            'merged_signal_return_artifact_path_mismatch',
            'merged_signal_return_artifact_hash_mismatch',
        }
    )
    return {
        'case': 'shared_evaluation_context_rejects_tampered_merged_artifact',
        'report_id': report_id,
        'step4_rc': proc.returncode,
        'self_quant_rc': sq_proc.returncode,
        'tampered_path': str(tampered_path),
        'self_quant_shared_context': shared_sq,
        'stdout_tail': tail(sq_proc.stdout),
        'stderr_tail': tail(sq_proc.stderr),
        'ok': bool(ok),
    }


def run_qlib_preflight_still_skips_missing_provider_with_shared_context_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_QLIB_SHARED_CONTEXT_PREFLIGHT'
    paths = create_step4_factor_csv_policy_fixture(root, report_id, 'sample_csv')
    handoff_path = root / 'objects' / 'handoff' / f'handoff_to_step4__{report_id}.json'
    handoff = read_json(handoff_path)
    handoff['evaluation_plan'] = {
        'backends': [
            {'name': 'self_quant_analyzer', 'mode': 'quick'},
            {'name': 'qlib_backtest', 'mode': 'native', 'provider_uri': str(root / 'missing_qlib_provider')},
        ],
        'metric_policy': 'extensible',
    }
    write_json(handoff_path, handoff)
    proc = run_step4_direct(root, report_id, extra_args=['--enable-shared-evaluation-context'])
    qlib_payload = read_json(root / 'evaluations' / report_id / 'qlib_backtest' / 'evaluation_payload.json')
    preflight = qlib_payload.get('qlib_preflight') or {}
    shared = qlib_payload.get('shared_evaluation_context') or {}
    ok = (
        proc.returncode == 0
        and qlib_payload.get('status') == 'skipped'
        and preflight.get('native_attempted') is False
        and preflight.get('status') == 'skipped_native_missing_provider'
        and shared.get('available') is True
        and shared.get('used') is False
    )
    return {
        'case': 'qlib_preflight_still_skips_missing_provider_with_shared_context',
        'report_id': report_id,
        'rc': proc.returncode,
        'qlib_preflight': preflight,
        'qlib_shared_context': shared,
        'stdout_tail': tail(proc.stdout),
        'stderr_tail': tail(proc.stderr),
        'ok': bool(ok),
    }


def run_throughput_profile_reports_shared_evaluation_context_case(root: Path) -> dict[str, Any]:
    report_id = 'PERF_SMOKE_THROUGHPUT_SHARED_CONTEXT'
    create_step4_factor_csv_policy_fixture(root, report_id, 'sample_csv')
    step4_proc = run_step4_direct(root, report_id, extra_args=['--enable-shared-evaluation-context'])
    output = root / 'throughput_profile_shared_context.json'
    proc = run_cmd([
        sys.executable,
        'scripts/run_factorforge_throughput_profile.py',
        '--root',
        str(root),
        '--report-id',
        report_id,
        '--output',
        str(output),
    ])
    payload = read_json(output) if output.exists() else {}
    codes = {item.get('code') for item in payload.get('diagnostics', []) if isinstance(item, dict)}
    shared = ((payload.get('step4') or {}).get('shared_evaluation_context') or {})
    ok = (
        step4_proc.returncode == 0
        and proc.returncode == 0
        and 'SHARED_EVALUATION_CONTEXT_BUILT' in codes
        and 'SHARED_EVALUATION_CONTEXT_USED_SELF_QUANT' in codes
        and ((shared.get('self_quant') or {}).get('used') is True)
    )
    return {
        'case': 'throughput_profile_reports_shared_evaluation_context',
        'report_id': report_id,
        'step4_rc': step4_proc.returncode,
        'profile_rc': proc.returncode,
        'diagnostic_codes': sorted(codes),
        'shared_evaluation_context': shared,
        'ok': bool(ok),
    }


def run_throughput_profile_reads_backend_timing_profile_case(root: Path) -> dict[str, Any]:
    ctx = ensure_step4_qlib_preflight_fixture(root)
    output = root / 'throughput_profile_backend_timing.json'
    proc = run_cmd([
        sys.executable,
        'scripts/run_factorforge_throughput_profile.py',
        '--root',
        str(root),
        '--report-id',
        ctx['report_id'],
        '--output',
        str(output),
    ])
    payload = read_json(output) if output.exists() else {}
    timing = ((payload.get('step4') or {}).get('backend_timing_profile') or {})
    qlib = ((timing.get('backends') or {}).get('qlib_native') or {})
    self_quant = ((timing.get('backends') or {}).get('self_quant_analyzer') or {})
    ok = (
        proc.returncode == 0
        and timing.get('version') == 'factorforge_step4_backend_timing_profile_v1'
        and self_quant.get('attempted') is True
        and qlib.get('attempted') is False
        and qlib.get('status') == 'skipped_native_missing_provider'
        and (payload.get('step4') or {}).get('qlib_native_attempted') is False
    )
    return {
        'case': 'throughput_profile_reads_backend_timing_profile',
        'report_id': ctx['report_id'],
        'rc': proc.returncode,
        'output_exists': output.exists(),
        'backend_timing_profile': timing,
        'ok': bool(ok),
    }


def run_non_tmp_selftest() -> dict[str, Any]:
    if os.getenv('FACTORFORGE_PERF_SMOKE_SKIP_NON_TMP_SELFTEST') == '1':
        return {'case': 'non_tmp_root_blocks', 'skipped': True, 'ok': True}
    env = os.environ.copy()
    env['FACTORFORGE_PERF_SMOKE_SKIP_NON_TMP_SELFTEST'] = '1'
    proc = subprocess.run(
        [sys.executable, 'scripts/run_factorforge_performance_smoke.py', '--fresh', '--root', '/Users/humphrey/tmp_factorforge_bad'],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    output = proc.stdout + proc.stderr
    return {
        'case': 'non_tmp_root_blocks',
        'rc': proc.returncode,
        'token_present': 'BLOCK_NON_TMP_FACTORFORGE_ROOT' in output,
        'ok': proc.returncode == 1 and 'BLOCK_NON_TMP_FACTORFORGE_ROOT' in output,
    }


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=None)
    ap.add_argument('--fresh', action='store_true')
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root or (Path('/tmp') / f'factorforge_performance_{datetime.now().strftime("%Y%m%d_%H%M%S")}')).expanduser()
    resolved = root.resolve()
    root_text = str(root)
    resolved_text = str(resolved)
    if not (root_text.startswith('/tmp/') or resolved_text.startswith('/tmp/') or resolved_text.startswith('/private/tmp/')):
        print(f'BLOCK_NON_TMP_FACTORFORGE_ROOT: {resolved}')
        return 1
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    before = snapshot_repo_files()
    cases = [
        run_py_compile(),
        run_operator_parity(),
        run_formula_evaluator_parity_case(),
        run_formula_evaluator_cache_case(),
        run_formula_evaluator_unsorted_case(),
        run_sort_contract_written_by_step3a_case(root),
        run_step3b_trusted_sort_contract_skips_full_sort_opt_in_case(root),
        run_step3b_sort_contract_default_path_unchanged_without_opt_in_case(root),
        run_step3b_sort_contract_fallback_on_row_count_mismatch_case(root),
        run_step3b_sort_contract_fallback_on_duplicate_key_case(root),
        run_step3b_sort_contract_fallback_on_unsorted_unsampled_inversion_case(root),
        run_step3b_sort_contract_output_parity_with_full_sort_case(root),
        run_operator_profile_basic_present_case(),
        run_operator_profile_alpha017_like_breakdown_case(),
        run_operator_profile_cache_hit_recorded_case(),
        run_polars_dependency_probe_case(),
        run_polars_rank_nan_parity_case(),
        run_polars_delta_nan_parity_case(),
        run_polars_arithmetic_nan_parity_case(),
        run_polars_alpha017_subset_parity_case(),
        run_polars_unsupported_operator_fallback_or_block_case(),
        run_polars_parity_failure_blocks_case(),
        run_polars_parity_failure_diagnostics_present_case(),
        run_ts_rank_default_disabled_large_case(),
        run_ts_rank_experimental_fast_parity_case(),
        run_ts_rank_candidate_small_parity_case(),
        run_ts_rank_candidate_medium_benchmark_case(root),
        run_ts_rank_candidate_alpha017_sample_readonly_case(root),
        run_ts_rank_candidate_non_tmp_root_blocks_case(),
        run_ts_rank_engine_default_is_pandas_case(root),
        run_ts_rank_engine_requires_explicit_enable_case(root),
        run_ts_rank_engine_invalid_blocks_case(root),
        run_ts_rank_engine_experimental_parity_passes_case(root),
        run_ts_rank_engine_parity_failure_blocks_case(root),
        run_ts_rank_engine_runtime_guard_blocks_case(root),
        run_ts_rank_engine_no_default_path_drift_case(),
        run_ts_rank_legacy_fast_env_ignored_case(root),
        run_ts_rank_legacy_fast_env_does_not_select_engine_with_new_gate_case(root),
        run_formula_kernel_default_path_remains_pandas_case(),
        run_formula_kernel_requires_explicit_enable_case(),
        run_formula_kernel_invalid_engine_blocks_case(),
        run_formula_kernel_rolling_mean_sum_parity_case(),
        run_formula_kernel_rolling_std_parity_case(),
        run_formula_kernel_ts_rank_candidate_parity_case(),
        run_formula_kernel_ts_rank_edge_parity_case(),
        run_formula_kernel_ts_rank_default_path_unchanged_case(),
        run_formula_kernel_ts_rank_engine_gate_coexists_case(),
        run_formula_kernel_argmin_argmax_parity_case(),
        run_formula_kernel_argmin_argmax_default_path_unchanged_case(),
        run_formula_kernel_default_numpy_ts_promoted_parity_case(),
        run_formula_kernel_default_numpy_ts_direct_caller_promoted_case(),
        run_formula_kernel_default_numpy_ts_rollback_env_restores_pandas_case(),
        run_formula_kernel_default_numpy_ts_std_excluded_case(),
        run_formula_kernel_default_numpy_ts_corr_cov_promoted_case(),
        run_formula_kernel_default_numpy_ts_corr_cov_speed_guard_case(),
        run_formula_kernel_corr_cov_single_group_rollback_case(),
        run_formula_kernel_parity_failure_blocks_case(root),
        run_formula_kernel_argmin_argmax_parity_failure_blocks_case(root),
        run_formula_kernel_ts_rank_parity_failure_blocks_case(root),
        run_formula_kernel_runtime_guard_blocks_case(root),
        run_formula_kernel_ts_rank_runtime_guard_blocks_case(root),
        run_step3b_formula_kernel_metadata_present_case(root),
        run_step3b_formula_kernel_argmin_argmax_metadata_case(root),
        run_step3b_formula_kernel_ts_rank_metadata_case(root),
        run_step3b_default_numpy_ts_metadata_case(root),
        run_step3b_default_numpy_ts_rollback_metadata_case(root),
        run_step3a_daily_parquet_contract_case(root),
        run_step3_daily_parquet_csv_schema_parity_case(root),
        run_step3_daily_large_schema_mismatch_block_case(root),
        run_step3a_daily_sample_csv_policy_case(root),
        run_step3a_daily_no_csv_policy_case(root),
        run_step3a_daily_sample_schema_mismatch_block_case(root),
        run_step3a_daily_no_csv_contract_stale_path_block_case(root),
        run_price_volume_plugin_uses_volume_case(),
        run_step3b_profile_case(root),
        run_step3b_factor_sample_csv_policy_case(root),
        run_step3b_factor_no_csv_policy_case(root),
        run_csv_policy_sample_csv_parquet_formal_evidence_case(root),
        run_csv_policy_no_csv_parquet_formal_evidence_case(root),
        run_csv_policy_full_csv_legacy_compat_case(root),
        run_validate_step3_accepts_no_csv_with_parquet_case(root),
        run_csv_policy_invalid_blocks_case(root),
        run_csv_policy_invalid_cli_blocks_case(root),
        run_step3b_prefers_daily_parquet_case(root),
        run_step3b_formula_engine_profile_case(root),
        run_step3b_operator_profile_metadata_present_case(root),
        run_operator_profile_disabled_metadata_present_case(root),
        run_step3b_polars_experimental_profile_case(root),
        run_self_quant_parity_case(root),
        run_self_quant_profile_case(root),
        run_step4_self_quant_prefers_daily_parquet_case(root),
        run_step4_daily_csv_fallback_case(root),
        run_step4_reuses_step3b_factor_parquet_case(root),
        run_step4_preserves_prior_step4_parquet_provenance_case(root),
        run_step4_respects_step3b_sample_csv_policy_case(root),
        run_step4_respects_step3b_no_csv_policy_case(root),
        run_step4_legacy_missing_csv_policy_full_csv_compat_case(root),
        run_step4_invalid_factor_csv_policy_blocks_case(root),
        run_step4_uses_parquet_when_full_csv_absent_case(root),
        run_validate_step4_accepts_no_csv_with_parquet_case(root),
        run_step4_qlib_preflight_skips_missing_provider_case(root),
        run_step4_backend_timing_profile_records_self_quant_case(root),
        run_step4_backend_timing_profile_records_qlib_skipped_case(root),
        run_step4_missing_qlib_provider_not_marked_success_case(root),
        run_step4_shared_evaluation_context_default_path_unchanged_case(root),
        run_step4_builds_shared_evaluation_context_opt_in_case(root),
        run_self_quant_uses_shared_evaluation_context_case(root),
        run_self_quant_shared_context_parity_with_legacy_path_case(root),
        run_shared_evaluation_context_rejected_on_identity_mismatch_case(root),
        run_shared_evaluation_context_rejects_tampered_merged_artifact_case(root),
        run_qlib_preflight_still_skips_missing_provider_with_shared_context_case(root),
        run_profile_script_readonly_case(root),
        run_throughput_profile_reads_step3b_step4_metadata_case(root),
        run_throughput_profile_flags_large_full_csv_case(root),
        run_throughput_profile_flags_step4_recompute_fallback_case(root),
        run_throughput_profile_handles_missing_artifacts_case(root),
        run_throughput_profile_blocks_non_tmp_output_case(root),
        run_throughput_profile_reports_csv_policy_case(root),
        run_throughput_profile_reports_sort_contract_case(root),
        run_operator_kernel_inventory_contract_case(root),
        run_operator_kernel_inventory_flags_hotspots_case(root),
        run_operator_kernel_inventory_classifies_talib_case(root),
        run_operator_kernel_inventory_blocks_non_tmp_output_case(root),
        run_operator_kernel_inventory_no_canonical_pollution_case(root),
        run_operator_candidate_benchmark_contract_case(root),
        run_operator_candidate_benchmark_argmin_argmax_parity_case(root),
        run_operator_candidate_benchmark_corr_cov_parity_case(root),
        run_operator_candidate_benchmark_corr_cov_semantic_profile_case(root),
        run_operator_candidate_benchmark_corr_cov_edge_parity_case(root),
        run_operator_candidate_benchmark_corr_cov_readonly_case(root),
        run_operator_candidate_benchmark_blocks_non_tmp_output_case(root),
        run_operator_candidate_benchmark_does_not_modify_formula_runtime_case(root),
        run_throughput_profile_reads_backend_timing_profile_case(root),
        run_throughput_profile_reports_shared_evaluation_context_case(root),
        run_step4_metadata_merge_case(root),
        run_non_tmp_selftest(),
    ]
    after = snapshot_repo_files()
    canonical_pollution = {'polluted': bool(after - before), 'new_files': sorted(after - before)}
    verdict = 'ACCEPT' if all(case.get('ok') for case in cases) and not canonical_pollution['polluted'] else 'BLOCK'
    summary = {
        'contract_version': 'factorforge_performance_smoke_v1',
        'created_at_utc': utc_now(),
        'factorforge_root': str(resolved),
        'root_is_tmp': True,
        'cases': cases,
        'canonical_pollution': canonical_pollution,
        'verdict': verdict,
        'notes': [
            'Synthetic /tmp-only smoke.',
            'No real factor research was run.',
            'No clean data was read or processed.',
        ],
    }
    summary_path = root / 'performance_smoke_summary.json'
    write_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f'[SUMMARY] {summary_path}')
    return 0 if verdict == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
