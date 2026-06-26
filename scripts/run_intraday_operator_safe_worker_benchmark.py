#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


def _load_script_module(filename: str, module_name: str) -> Any:
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load script module: {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run preflight, worker benchmark, and worker benchmark validation as one safe read-only workflow.')
    parser.add_argument('--input-root', required=True)
    parser.add_argument('--input-format', choices=['prepared_minute_bar_v1', 'raw_minute_bar'], required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--label', default='safe_worker_intraday_operator_benchmark')
    parser.add_argument('--evidence-scope', choices=['bounded_worker', 'production_scale', 'full_is'], default='bounded_worker')
    parser.add_argument('--start')
    parser.add_argument('--end')
    parser.add_argument('--dates')
    parser.add_argument('--row-limit', type=int, default=0)
    parser.add_argument('--window', type=int, default=20)
    parser.add_argument('--min-row-count', type=int, default=100000)
    parser.add_argument('--include-array-grouped', action='store_true')
    parser.add_argument('--include-process-sharded-array-grouped', action='store_true')
    parser.add_argument('--include-numba-grouped', action='store_true')
    parser.add_argument('--include-threaded-grouped', action='store_true')
    parser.add_argument('--include-terminal-rolling-corr', action='store_true')
    parser.add_argument('--include-ema-state', action='store_true')
    parser.add_argument('--include-terminal-ema-state', action='store_true')
    parser.add_argument('--include-cpv-operator', action='store_true')
    parser.add_argument('--cpv-backend', default='array_grouped')
    parser.add_argument('--cpv-terminal-only', action='store_true')
    parser.add_argument('--max-workers', type=int, default=1)
    parser.add_argument('--max-load-per-cpu', type=float, default=0.75)
    parser.add_argument('--min-available-memory-gb', type=float, default=16.0)
    parser.add_argument('--max-protected-process-cpu', type=float, default=25.0)
    parser.add_argument('--protected-process-pattern', action='append', default=[])
    parser.add_argument('--preflight-load1', type=float)
    parser.add_argument('--preflight-cpu-count', type=int)
    parser.add_argument('--preflight-available-memory-gb', type=float)
    parser.add_argument('--preflight-process-snapshot-json')
    return parser.parse_args(argv)


def _append_if(args: list[str], flag: str, value: str | None) -> None:
    if value:
        args.extend([flag, value])


def _normalize_input_root(value: str) -> str:
    return value.rstrip('/') if value.startswith('s3://') else str(Path(value).expanduser())


def _read_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text())


def _summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        'verdict': payload.get('verdict'),
        'issues': payload.get('issues') or [],
        'metrics': payload.get('metrics') or {},
    }


def _safe_bundle(
    *,
    verdict: str,
    label: str,
    evidence_scope: str,
    output_dir: Path,
    blocked_stage: str | None,
    preflight_path: Path,
    preflight: dict[str, Any],
    worker_bundle_path: Path | None = None,
    worker_bundle: dict[str, Any] | None = None,
    worker_validation_path: Path | None = None,
    worker_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    worker_bundle = worker_bundle or {}
    worker_validation = worker_validation or {}
    return {
        'verdict': verdict,
        'label': label,
        'evidence_scope': worker_bundle.get('evidence_scope') or worker_validation.get('evidence_scope') or evidence_scope,
        'output_dir': str(output_dir),
        'blocked_stage': blocked_stage,
        'preflight_path': str(preflight_path),
        'preflight_summary': _summary(preflight),
        'worker_benchmark_bundle_path': str(worker_bundle_path) if worker_bundle_path else None,
        'worker_benchmark_summary': {
            'verdict': worker_bundle.get('verdict'),
            'sample_row_count': (worker_bundle.get('sample_summary') or {}).get('row_count'),
            'gate_verdict': (worker_bundle.get('gate_summary') or {}).get('verdict'),
            'validation_verdict': (worker_bundle.get('gate_summary') or {}).get('validation_verdict'),
            'evidence_scope': worker_bundle.get('evidence_scope'),
        } if worker_bundle else None,
        'worker_validation_path': str(worker_validation_path) if worker_validation_path else None,
        'worker_validation_summary': {
            'verdict': worker_validation.get('verdict'),
            'issues': worker_validation.get('issues') or [],
            'input_row_count': worker_validation.get('input_row_count'),
            'promotion_candidate_count': worker_validation.get('promotion_candidate_count'),
            'evidence_scope': worker_validation.get('evidence_scope'),
        } if worker_validation else None,
        'safety': {
            'starts_backfill': False,
            'writes_datamart': False,
            'writes_catalog': False,
            'production_loop_side_effect': False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    label = str(args.label)
    preflight_path = output_dir / f'{label}.preflight.json'
    worker_bundle_path = output_dir / f'{label}.worker_benchmark.bundle.json'
    worker_validation_path = output_dir / f'{label}.worker_benchmark.validation.json'
    safe_bundle_path = output_dir / f'{label}.safe_worker_benchmark.bundle.json'

    preflight_runner = _load_script_module('run_intraday_operator_worker_preflight.py', 'run_intraday_operator_worker_preflight')
    worker_runner = _load_script_module('run_intraday_operator_worker_benchmark.py', 'run_intraday_operator_worker_benchmark')
    worker_validator = _load_script_module('validate_intraday_operator_worker_benchmark.py', 'validate_intraday_operator_worker_benchmark')

    preflight_args = [
        '--output-path',
        str(preflight_path),
        '--max-load-per-cpu',
        str(float(args.max_load_per_cpu)),
        '--min-available-memory-gb',
        str(float(args.min_available_memory_gb)),
        '--max-protected-process-cpu',
        str(float(args.max_protected_process_cpu)),
    ]
    for pattern in args.protected_process_pattern or []:
        preflight_args.extend(['--protected-process-pattern', str(pattern)])
    if args.preflight_load1 is not None:
        preflight_args.extend(['--load1', str(float(args.preflight_load1))])
    if args.preflight_cpu_count is not None:
        preflight_args.extend(['--cpu-count', str(int(args.preflight_cpu_count))])
    if args.preflight_available_memory_gb is not None:
        preflight_args.extend(['--available-memory-gb', str(float(args.preflight_available_memory_gb))])
    if args.preflight_process_snapshot_json:
        preflight_args.extend(['--process-snapshot-json', str(args.preflight_process_snapshot_json)])

    preflight_exit = preflight_runner.main(preflight_args)
    preflight = _read_json(preflight_path)
    if preflight_exit != 0 or preflight.get('verdict') != 'ACCEPT':
        bundle = _safe_bundle(
            verdict='BLOCK',
            label=label,
            evidence_scope=str(args.evidence_scope),
            output_dir=output_dir,
            blocked_stage='preflight',
            preflight_path=preflight_path,
            preflight=preflight,
        )
        safe_bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'verdict': 'BLOCK', 'blocked_stage': 'preflight', 'bundle_path': str(safe_bundle_path)}, ensure_ascii=False, indent=2))
        return 1

    worker_args = [
        '--input-root',
        _normalize_input_root(str(args.input_root)),
        '--input-format',
        str(args.input_format),
        '--output-dir',
        str(output_dir),
        '--label',
        label,
        '--evidence-scope',
        str(args.evidence_scope),
        '--window',
        str(int(args.window)),
        '--min-row-count',
        str(int(args.min_row_count)),
        '--max-workers',
        str(int(args.max_workers)),
        '--preflight-path',
        str(preflight_path),
    ]
    _append_if(worker_args, '--start', args.start)
    _append_if(worker_args, '--end', args.end)
    _append_if(worker_args, '--dates', args.dates)
    if int(args.row_limit or 0) > 0:
        worker_args.extend(['--row-limit', str(int(args.row_limit))])
    if args.include_array_grouped:
        worker_args.append('--include-array-grouped')
    if args.include_process_sharded_array_grouped:
        worker_args.append('--include-process-sharded-array-grouped')
    if args.include_numba_grouped:
        worker_args.append('--include-numba-grouped')
    if args.include_threaded_grouped:
        worker_args.append('--include-threaded-grouped')
    if args.include_terminal_rolling_corr:
        worker_args.append('--include-terminal-rolling-corr')
    if args.include_ema_state:
        worker_args.append('--include-ema-state')
    if args.include_terminal_ema_state:
        worker_args.append('--include-terminal-ema-state')
    if args.include_cpv_operator:
        worker_args.append('--include-cpv-operator')
        worker_args.extend(['--cpv-backend', str(args.cpv_backend)])
    if args.cpv_terminal_only:
        worker_args.append('--cpv-terminal-only')

    worker_exit = worker_runner.main(worker_args)
    worker_bundle = _read_json(worker_bundle_path)
    if worker_exit != 0 or worker_bundle.get('verdict') != 'ACCEPT':
        bundle = _safe_bundle(
            verdict='BLOCK',
            label=label,
            evidence_scope=str(args.evidence_scope),
            output_dir=output_dir,
            blocked_stage='worker_benchmark',
            preflight_path=preflight_path,
            preflight=preflight,
            worker_bundle_path=worker_bundle_path,
            worker_bundle=worker_bundle,
        )
        safe_bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'verdict': 'BLOCK', 'blocked_stage': 'worker_benchmark', 'bundle_path': str(safe_bundle_path)}, ensure_ascii=False, indent=2))
        return 1

    validation_exit = worker_validator.main([
        '--bundle-path',
        str(worker_bundle_path),
        '--output-path',
        str(worker_validation_path),
        '--min-row-count',
        str(int(args.min_row_count)),
        '--evidence-scope',
        str(args.evidence_scope),
    ])
    worker_validation = _read_json(worker_validation_path)
    verdict = 'ACCEPT' if validation_exit == 0 and worker_validation.get('verdict') == 'ACCEPT' else 'BLOCK'
    bundle = _safe_bundle(
        verdict=verdict,
        label=label,
        evidence_scope=str(args.evidence_scope),
        output_dir=output_dir,
        blocked_stage=None if verdict == 'ACCEPT' else 'worker_validation',
        preflight_path=preflight_path,
        preflight=preflight,
        worker_bundle_path=worker_bundle_path,
        worker_bundle=worker_bundle,
        worker_validation_path=worker_validation_path,
        worker_validation=worker_validation,
    )
    safe_bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'verdict': verdict, 'bundle_path': str(safe_bundle_path)}, ensure_ascii=False, indent=2))
    return 0 if verdict == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
