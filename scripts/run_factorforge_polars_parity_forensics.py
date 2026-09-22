#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.formula.evaluator import _eval_cached, _prepare_optimized_frame
from factor_factory.formula.kernels import default_kernel_profile, resolve_formula_kernel_engine
from factor_factory.formula.polars_evaluator import (
    _eval_column,
    _node_key,
    _parity_fields,
    first_unsupported_operator,
    polars_dependency_available,
    resolve_formula_ir_for_parquet_schema,
)

VERSION = 'factorforge_polars_parity_forensics_v1'
CANONICAL_DIRS = ['objects', 'runs', 'evaluations', 'generated_code', 'archive', 'factorforge', 'data/clean']


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def is_tmp_path(path: Path) -> bool:
    text = str(path.expanduser().resolve())
    return text.startswith('/tmp/') or text.startswith('/private/tmp/')


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def snapshot_canonical_files(root: Path) -> set[str]:
    out: set[str] = set()
    for raw_dir in CANONICAL_DIRS:
        base = root / raw_dir
        if not base.exists():
            continue
        for item in base.rglob('*'):
            if item.is_file():
                out.add(str(item.relative_to(root)))
    return out


def extract_formula_ir(payload: dict[str, Any]) -> dict[str, Any] | None:
    canonical = payload.get('canonical_spec')
    if isinstance(canonical, dict) and isinstance(canonical.get('formula_ir'), dict):
        return canonical['formula_ir']
    if isinstance(payload.get('formula_ir'), dict):
        return payload['formula_ir']
    return None


def find_factor_spec(root: Path, report_id: str) -> Path:
    path = root / 'objects' / 'factor_spec_master' / f'factor_spec_master__{report_id}.json'
    if path.exists():
        return path
    raise FileNotFoundError(f'BLOCK_POLARS_PARITY_FORENSICS_MISSING_FACTOR_SPEC:{path}')


def find_daily_parquet(root: Path, report_id: str) -> Path:
    candidates = [
        root / 'runs' / report_id / 'step3a_local_inputs' / f'daily_input__{report_id}.parquet',
        root / 'runs' / report_id / f'daily_input__{report_id}.parquet',
        root / 'archive' / report_id / 'runs' / 'step3a_local_inputs' / f'daily_input__{report_id}.parquet',
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    run_dir = root / 'runs' / report_id
    if run_dir.exists():
        matches = sorted(run_dir.rglob('daily_input__*.parquet'))
        if matches:
            return matches[0]
    archive_dir = root / 'archive' / report_id
    if archive_dir.exists():
        matches = sorted(archive_dir.rglob('daily_input__*.parquet'))
        if matches:
            return matches[0]
    raise FileNotFoundError(f'BLOCK_POLARS_PARITY_FORENSICS_MISSING_DAILY_PARQUET:{report_id}')


def collect_nodes(root_node: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(node: dict[str, Any], path: str, depth: int) -> None:
        for idx, arg in enumerate(node.get('args') or []):
            if isinstance(arg, dict):
                visit(arg, f'{path}.args[{idx}]', depth + 1)
        key = _node_key(node)
        if key in seen:
            return
        seen.add(key)
        typ = str(node.get('type') or 'unknown')
        nodes.append({
            'node': node,
            'node_id': key,
            'path': path,
            'depth': int(depth),
            'node_type': typ,
            'operator': node.get('operator') if typ == 'operator' else None,
            'field': node.get('resolved_field') or node.get('name') if typ == 'field' else None,
            'constant': node.get('value') if typ == 'constant' else None,
        })

    visit(root_node, 'root', 0)
    return nodes


def scalar_to_series(value: Any, index: pd.Index) -> pd.Series:
    if isinstance(value, pd.Series):
        return pd.to_numeric(value, errors='coerce')
    return pd.Series([float(value)] * len(index), index=index, dtype='float64')


def frame_from_values(keys: pd.DataFrame, values: Any) -> pd.DataFrame:
    out = keys.copy()
    out['factor_value'] = scalar_to_series(values, keys.index).to_numpy(dtype='float64', copy=False)
    return out


def normalize_number(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        if np.isnan(value):
            return None
        if np.isposinf(value):
            return 'inf'
        if np.isneginf(value):
            return '-inf'
        return value
    return value


def top_diff_samples(reference: pd.DataFrame, candidate: pd.DataFrame, *, limit: int = 5) -> list[dict[str, Any]]:
    ref = reference.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    cand = candidate.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    ref_values = pd.to_numeric(ref['factor_value'], errors='coerce')
    cand_values = pd.to_numeric(cand['factor_value'], errors='coerce')
    valid = ref_values.notna() & cand_values.notna()
    if not bool(valid.any()):
        return []
    diffs = (ref_values[valid] - cand_values[valid]).abs().sort_values(ascending=False)
    samples: list[dict[str, Any]] = []
    for idx in diffs.head(limit).index:
        samples.append({
            'ts_code': str(ref.loc[idx, 'ts_code']),
            'trade_date': str(ref.loc[idx, 'trade_date']),
            'reference_value': normalize_number(ref_values.loc[idx]),
            'candidate_value': normalize_number(cand_values.loc[idx]),
            'abs_diff': normalize_number(abs(ref_values.loc[idx] - cand_values.loc[idx])),
        })
    return samples


def parity_passed(parity: dict[str, Any], tolerance: float) -> bool:
    max_abs_diff = parity.get('max_abs_diff')
    if isinstance(max_abs_diff, str):
        diff_ok = False
    else:
        diff_ok = float(max_abs_diff if max_abs_diff is not None else float('inf')) <= float(tolerance)
    rank_corr = parity.get('rank_corr')
    rank_ok = rank_corr is None or float(rank_corr) >= 0.999999
    return bool(
        parity.get('row_count_equal') is True
        and parity.get('key_order_equal') is True
        and parity.get('nan_mask_equal') is True
        and diff_ok
        and rank_ok
    )


def evaluate_node_profiles(resolved_ir: dict[str, Any], daily_path: Path, selected_columns: list[str], *, tolerance: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not polars_dependency_available():
        raise ModuleNotFoundError('BLOCK_POLARS_PARITY_FORENSICS_POLARS_MISSING')

    import polars as pl

    raw = pd.read_parquet(daily_path, columns=selected_columns)
    for key in ['ts_code', 'trade_date']:
        raw[key] = raw[key].astype(str)
    working, input_presorted = _prepare_optimized_frame(raw)
    keys = working[['ts_code', 'trade_date']].copy()
    nodes = collect_nodes(resolved_ir['root'])

    kernel_config = resolve_formula_kernel_engine()
    pandas_stats: dict[str, Any] = {
        'cache_hits': 0,
        'cache_misses': 0,
        'kernel_profile': default_kernel_profile(kernel_config),
    }
    pandas_cache: dict[str, Any] = {}
    pandas_values: dict[str, Any] = {}
    for meta in nodes:
        pandas_values[meta['node_id']] = _eval_cached(
            meta['node'],
            working,
            pandas_cache,
            pandas_stats,
            formula_kernel_config=kernel_config,
        )

    lf = (
        pl.scan_parquet(str(daily_path))
        .select(selected_columns)
        .with_columns([
            pl.col('ts_code').cast(pl.Utf8),
            pl.col('trade_date').cast(pl.Utf8),
        ])
        .sort(['ts_code', 'trade_date'])
    )
    pl_cache: dict[str, str] = {}
    node_columns: dict[str, str] = {}
    for meta in nodes:
        lf, col = _eval_column(meta['node'], lf, pl, pl_cache)
        node_columns[meta['node_id']] = col
    select_exprs = [pl.col('ts_code'), pl.col('trade_date')]
    for node_id, col in node_columns.items():
        select_exprs.append(pl.col(col).alias(f'node_{node_id}'))
    collected = lf.select(select_exprs).collect().to_pandas()

    profiles: list[dict[str, Any]] = []
    for ordinal, meta in enumerate(nodes):
        node_id = meta['node_id']
        reference = frame_from_values(keys, pandas_values[node_id])
        candidate = collected[['ts_code', 'trade_date', f'node_{node_id}']].rename(columns={f'node_{node_id}': 'factor_value'})
        candidate['factor_value'] = pd.to_numeric(candidate['factor_value'], errors='coerce')
        parity = _parity_fields(reference, candidate, tolerance=float('inf'))
        node_ok = parity_passed(parity, tolerance)
        profiles.append({
            'ordinal': int(ordinal),
            'node_id': node_id,
            'path': meta['path'],
            'depth': meta['depth'],
            'node_type': meta['node_type'],
            'operator': meta['operator'],
            'field': meta['field'],
            'constant': normalize_number(meta['constant']),
            'parity_pass': bool(node_ok),
            'top_abs_diff_samples': [] if node_ok else top_diff_samples(reference, candidate),
            'parity': {key: normalize_number(value) for key, value in parity.items()},
        })

    context = {
        'input_presorted': bool(input_presorted),
        'row_count': int(len(working)),
        'selected_columns': selected_columns,
        'pandas_kernel_profile': pandas_stats.get('kernel_profile') or {},
    }
    return profiles, context


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).expanduser().resolve()
    before = snapshot_canonical_files(root)
    spec_path = find_factor_spec(root, args.report_id)
    spec_payload = read_json(spec_path)
    formula_ir = extract_formula_ir(spec_payload)
    if not isinstance(formula_ir, dict):
        raise ValueError(f'BLOCK_POLARS_PARITY_FORENSICS_MISSING_FORMULA_IR:{spec_path}')
    unsupported = first_unsupported_operator(formula_ir)
    daily_path = find_daily_parquet(root, args.report_id)
    resolved_ir, selected_columns, parquet_schema = resolve_formula_ir_for_parquet_schema(formula_ir, daily_path)

    if unsupported is not None:
        node_profiles: list[dict[str, Any]] = []
        context: dict[str, Any] = {'selected_columns': selected_columns, 'row_count': None, 'input_presorted': None}
    else:
        node_profiles, context = evaluate_node_profiles(resolved_ir, daily_path, selected_columns, tolerance=float(args.tolerance))

    first_divergent = next((profile for profile in node_profiles if profile.get('parity_pass') is False), None)
    after = snapshot_canonical_files(root)
    pollution = sorted(after - before)
    verdict = 'ACCEPT'
    if unsupported is not None:
        verdict = 'UNSUPPORTED_OPERATOR'
    elif first_divergent is not None:
        verdict = 'DIVERGENCE_FOUND'
    if pollution:
        verdict = 'BLOCK'
    return {
        'version': VERSION,
        'created_at_utc': utc_now(),
        'root': str(root),
        'report_id': args.report_id,
        'read_only': True,
        'factor_spec_path': str(spec_path),
        'daily_parquet_path': str(daily_path),
        'parquet_schema': parquet_schema,
        'tolerance': float(args.tolerance),
        'unsupported_operator': unsupported,
        **context,
        'node_profile_count': int(len(node_profiles)),
        'node_profiles': node_profiles,
        'first_divergent_node': first_divergent,
        'canonical_pollution': bool(pollution),
        'canonical_pollution_new_files': pollution,
        'verdict': verdict,
    }


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Diagnose pandas-vs-lazy-Polars Formula-IR parity at node level.')
    ap.add_argument('--root', default=str(REPO_ROOT))
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--tolerance', type=float, default=1e-8)
    ap.add_argument('--allow-non-tmp-output', action='store_true')
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    output = Path(args.output).expanduser()
    if not args.allow_non_tmp_output and not is_tmp_path(output):
        print(f'BLOCK_POLARS_PARITY_FORENSICS_NON_TMP_OUTPUT: {output}')
        return 1
    payload = build_payload(args)
    write_json(output, payload)
    print(json.dumps({
        'output': str(output),
        'verdict': payload.get('verdict'),
        'first_divergent_node': (payload.get('first_divergent_node') or {}).get('node_id') if isinstance(payload.get('first_divergent_node'), dict) else None,
    }, ensure_ascii=False))
    return 1 if payload.get('verdict') == 'BLOCK' else 0


if __name__ == '__main__':
    raise SystemExit(main())
