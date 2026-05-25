#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.formula.evaluator import evaluate_formula_frame
from factor_factory.formula.polars_evaluator import (
    _parity_fields,
    assert_polars_result_parity,
    evaluate_formula_parquet_polars_experimental,
    first_unsupported_operator,
    polars_dependency_available,
    resolve_formula_ir_for_parquet_schema,
)

VERSION = 'factorforge_polars_adaptive_replay_v1'
CANONICAL_DIRS = ['objects', 'runs', 'evaluations', 'generated_code', 'archive', 'factorforge', 'data/clean']


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def is_tmp_path(path: Path) -> bool:
    text = str(path.expanduser().resolve())
    return text.startswith('/tmp/') or text.startswith('/private/tmp/')


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


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


def find_daily_parquet(root: Path, report_id: str) -> Path | None:
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
    return None


def iter_factor_specs(root: Path) -> list[tuple[str, Path, dict[str, Any]]]:
    specs: list[tuple[str, Path, dict[str, Any]]] = []
    spec_root = root / 'objects' / 'factor_spec_master'
    if not spec_root.exists():
        return specs
    for path in sorted(spec_root.glob('factor_spec_master__*.json')):
        payload = read_json(path)
        report_id = str(payload.get('report_id') or path.stem.replace('factor_spec_master__', ''))
        formula_ir = extract_formula_ir(payload)
        if isinstance(formula_ir, dict) and formula_ir.get('parse_status') == 'success':
            specs.append((report_id, path, formula_ir))
    return specs


def run_replay_case(root: Path, report_id: str, spec_path: Path, formula_ir: dict[str, Any], *, tolerance: float) -> dict[str, Any]:
    daily_path = find_daily_parquet(root, report_id)
    base: dict[str, Any] = {
        'report_id': report_id,
        'factor_spec_path': str(spec_path),
        'daily_parquet_path': str(daily_path) if daily_path else None,
        'operator_set': sorted(formula_ir.get('operator_set') or []),
        'polars_candidate': False,
        'polars_used': False,
        'polars_skip_reason': None,
        'parity_pass': None,
    }
    if daily_path is None:
        return {**base, 'status': 'skipped', 'polars_skip_reason': 'daily_parquet_missing'}
    unsupported = first_unsupported_operator(formula_ir)
    if unsupported is not None:
        return {**base, 'status': 'skipped', 'polars_skip_reason': f'unsupported_operator:{unsupported}'}
    if not polars_dependency_available():
        return {**base, 'status': 'skipped', 'polars_skip_reason': 'polars_dependency_missing'}

    try:
        resolved_ir, selected_columns, _schema = resolve_formula_ir_for_parquet_schema(formula_ir, daily_path)
    except Exception as exc:
        return {**base, 'status': 'skipped', 'polars_skip_reason': str(exc)}

    started = time.perf_counter()
    frame = pd.read_parquet(daily_path, columns=selected_columns)
    for key in ['ts_code', 'trade_date']:
        frame[key] = frame[key].astype(str)
    pandas_read_seconds = time.perf_counter() - started
    started = time.perf_counter()
    pandas_result, pandas_profile = evaluate_formula_frame(resolved_ir, frame, engine='optimized', return_profile=True)
    pandas_seconds = time.perf_counter() - started

    started = time.perf_counter()
    polars_result, polars_profile = evaluate_formula_parquet_polars_experimental(resolved_ir, daily_path, return_profile=True)
    polars_seconds = time.perf_counter() - started
    try:
        parity = assert_polars_result_parity(pandas_result, polars_result, tolerance=tolerance)
        parity_pass = True
        parity_error = None
    except AssertionError as exc:
        parity = _parity_fields(pandas_result, polars_result, tolerance=float('inf'))
        parity_pass = False
        parity_error = str(exc)

    return {
        **base,
        'status': 'benchmarked',
        'polars_candidate': True,
        'polars_used': polars_profile.get('polars_used') is True,
        'polars_execution_path': polars_profile.get('polars_execution_path'),
        'rows': int(len(polars_result)),
        'pandas_read_seconds': float(pandas_read_seconds),
        'pandas_compute_seconds': float(pandas_seconds),
        'polars_lazy_seconds': float(polars_seconds),
        'speedup_polars_vs_pandas': float(pandas_seconds / polars_seconds) if polars_seconds > 0 else None,
        'selected_columns': selected_columns,
        'parity_pass': parity_pass,
        'parity_error': parity_error,
        'parity': parity,
        'pandas_kernel_profile': pandas_profile.get('kernel_profile') or {},
    }


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).expanduser().resolve()
    before = snapshot_canonical_files(root)
    cases: list[dict[str, Any]] = []
    missing_daily_count = 0
    scanned_spec_count = 0
    for report_id, spec_path, formula_ir in iter_factor_specs(root):
        scanned_spec_count += 1
        if find_daily_parquet(root, report_id) is None and not args.include_missing_daily:
            missing_daily_count += 1
            continue
        cases.append(run_replay_case(root, report_id, spec_path, formula_ir, tolerance=float(args.tolerance)))
        if len(cases) >= max(int(args.max_cases), 0):
            break
    after = snapshot_canonical_files(root)
    pollution = sorted(after - before)
    benchmarked = [case for case in cases if case.get('status') == 'benchmarked']
    supported = [case for case in cases if case.get('polars_candidate') is True]
    unsupported = [case for case in cases if case.get('polars_candidate') is False]
    return {
        'version': VERSION,
        'created_at_utc': utc_now(),
        'root': str(root),
        'read_only': True,
        'max_cases': int(args.max_cases),
        'scanned_spec_count': int(scanned_spec_count),
        'missing_daily_skipped_count': int(missing_daily_count),
        'case_count': len(cases),
        'benchmarked_count': len(benchmarked),
        'polars_candidate_count': len(supported),
        'polars_non_candidate_count': len(unsupported),
        'cases': cases,
        'canonical_pollution': bool(pollution),
        'canonical_pollution_new_files': pollution,
        'diagnostics': [
            {'code': 'POLARS_ADAPTIVE_REPLAY_READ_ONLY'},
            {'code': 'POLARS_CANDIDATES_FOUND', 'count': len(supported)},
            {'code': 'POLARS_NON_CANDIDATES_FOUND', 'count': len(unsupported)},
        ],
        'verdict': 'ACCEPT' if all(case.get('parity_pass') is not False for case in cases) and not pollution else 'BLOCK',
    }


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Replay existing Formula-IR artifacts through pandas and lazy Polars for adaptive policy evidence.')
    ap.add_argument('--root', default=str(REPO_ROOT), help='Factor Forge root/repo containing objects/ and runs/.')
    ap.add_argument('--output', required=True)
    ap.add_argument('--max-cases', type=int, default=5)
    ap.add_argument('--tolerance', type=float, default=1e-8)
    ap.add_argument('--include-missing-daily', action='store_true')
    ap.add_argument('--allow-non-tmp-output', action='store_true')
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    output = Path(args.output).expanduser()
    if not args.allow_non_tmp_output and not is_tmp_path(output):
        print(f'BLOCK_POLARS_ADAPTIVE_REPLAY_NON_TMP_OUTPUT: {output}')
        return 1
    payload = build_payload(args)
    write_json(output, payload)
    print(json.dumps({'output': str(output), 'verdict': payload.get('verdict'), 'case_count': payload.get('case_count')}, ensure_ascii=False))
    return 0 if payload.get('verdict') == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
