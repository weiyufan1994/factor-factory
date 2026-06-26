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
    parser = argparse.ArgumentParser(description='Build a bounded minute sample and run the read-only intraday operator benchmark gate.')
    parser.add_argument('--input-root', required=True)
    parser.add_argument('--input-format', choices=['prepared_minute_bar_v1', 'raw_minute_bar'], required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--label', default='worker_intraday_operator_benchmark')
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
    parser.add_argument('--preflight-path')
    return parser.parse_args(argv)


def _append_if(args: list[str], flag: str, value: str | None) -> None:
    if value:
        args.extend([flag, value])


def _normalize_input_root(value: str) -> str:
    return value.rstrip('/') if value.startswith('s3://') else str(Path(value).expanduser())


def _bundle_payload(
    *,
    label: str,
    evidence_scope: str,
    sample_proof: dict[str, Any],
    sample_proof_path: Path,
    sample_parquet_path: Path,
    gate_bundle: dict[str, Any],
    gate_bundle_path: Path,
    output_dir: Path,
    preflight: dict[str, Any] | None = None,
    preflight_path: Path | None = None,
) -> dict[str, Any]:
    sample_ok = sample_proof.get('verdict') == 'ACCEPT'
    gate_ok = gate_bundle.get('verdict') == 'ACCEPT'
    gate_validation = gate_bundle.get('validation_summary') or {}
    gate_profile = gate_bundle.get('profile_summary') or {}
    sample_safety = sample_proof.get('safety') or {}
    gate_safety = gate_bundle.get('safety') or {}
    return {
        'verdict': 'ACCEPT' if sample_ok and gate_ok else 'BLOCK',
        'label': label,
        'evidence_scope': evidence_scope,
        'output_dir': str(output_dir),
        'sample_parquet_path': str(sample_parquet_path),
        'sample_proof_path': str(sample_proof_path),
        'gate_bundle_path': str(gate_bundle_path),
        'gate_profile_path': gate_bundle.get('profile_path'),
        'gate_validation_path': gate_bundle.get('validation_path'),
        'preflight_path': str(preflight_path) if preflight_path else None,
        'preflight_summary': {
            'verdict': preflight.get('verdict'),
            'issues': preflight.get('issues') or [],
            'metrics': preflight.get('metrics') or {},
        } if preflight else None,
        'sample_summary': {
            'verdict': sample_proof.get('verdict'),
            'input_format': sample_proof.get('input_format'),
            'semantic_scope': sample_proof.get('semantic_scope'),
            'row_count': sample_proof.get('row_count'),
            'date_count': sample_proof.get('date_count'),
            'ticker_count': sample_proof.get('ticker_count'),
            'duplicate_key_count': sample_proof.get('duplicate_key_count'),
            'price_source': sample_proof.get('price_source'),
            'volume_source': sample_proof.get('volume_source'),
        },
        'gate_summary': {
            'verdict': gate_bundle.get('verdict'),
            'profile_verdict': gate_profile.get('verdict'),
            'validation_verdict': gate_validation.get('verdict'),
            'validation_issues': gate_validation.get('issues') or [],
            'benchmark_scope': gate_profile.get('benchmark_scope'),
            'default_replacement_verdict': gate_profile.get('default_replacement_verdict'),
            'production_default_allowed': gate_profile.get('production_default_allowed'),
            'performance_candidates': gate_profile.get('performance_candidates') or [],
        },
        'safety': {
            'read_only_input': sample_safety.get('read_only_input') is True,
            'starts_backfill': bool(sample_safety.get('starts_backfill') or gate_safety.get('starts_backfill')),
            'writes_datamart': bool(sample_safety.get('writes_datamart') or gate_safety.get('writes_datamart')),
            'writes_catalog': bool(sample_safety.get('writes_catalog')),
            'production_loop_side_effect': bool(
                sample_safety.get('production_loop_side_effect') or gate_safety.get('production_loop_side_effect')
            ),
        },
    }


def _blocked_preflight_bundle(
    *,
    label: str,
    evidence_scope: str,
    output_dir: Path,
    preflight: dict[str, Any],
    preflight_path: Path,
) -> dict[str, Any]:
    safety = preflight.get('safety') or {}
    return {
        'verdict': 'BLOCK',
        'label': label,
        'evidence_scope': evidence_scope,
        'output_dir': str(output_dir),
        'preflight_path': str(preflight_path),
        'preflight_summary': {
            'verdict': preflight.get('verdict'),
            'issues': preflight.get('issues') or [],
            'metrics': preflight.get('metrics') or {},
        },
        'blocked_reason': 'worker_preflight_not_accept',
        'sample_parquet_path': None,
        'sample_proof_path': None,
        'gate_bundle_path': None,
        'safety': {
            'read_only_input': True,
            'starts_backfill': bool(safety.get('starts_backfill')),
            'writes_datamart': bool(safety.get('writes_datamart')),
            'writes_catalog': bool(safety.get('writes_catalog')),
            'production_loop_side_effect': bool(safety.get('production_loop_side_effect')),
        },
    }


def _blocked_sample_bundle(
    *,
    label: str,
    evidence_scope: str,
    output_dir: Path,
    sample_proof: dict[str, Any],
    sample_proof_path: Path,
    sample_parquet_path: Path,
    preflight: dict[str, Any] | None = None,
    preflight_path: Path | None = None,
) -> dict[str, Any]:
    sample_safety = sample_proof.get('safety') or {}
    return {
        'verdict': 'BLOCK',
        'label': label,
        'evidence_scope': evidence_scope,
        'output_dir': str(output_dir),
        'blocked_reason': 'sample_builder_not_accept',
        'sample_parquet_path': str(sample_parquet_path),
        'sample_proof_path': str(sample_proof_path),
        'gate_bundle_path': None,
        'preflight_path': str(preflight_path) if preflight_path else None,
        'preflight_summary': {
            'verdict': preflight.get('verdict'),
            'issues': preflight.get('issues') or [],
            'metrics': preflight.get('metrics') or {},
        } if preflight else None,
        'sample_summary': {
            'verdict': sample_proof.get('verdict'),
            'input_format': sample_proof.get('input_format'),
            'semantic_scope': sample_proof.get('semantic_scope'),
            'row_count': sample_proof.get('row_count'),
            'date_count': sample_proof.get('date_count'),
            'ticker_count': sample_proof.get('ticker_count'),
            'duplicate_key_count': sample_proof.get('duplicate_key_count'),
        },
        'safety': {
            'read_only_input': sample_safety.get('read_only_input') is True,
            'starts_backfill': bool(sample_safety.get('starts_backfill')),
            'writes_datamart': bool(sample_safety.get('writes_datamart')),
            'writes_catalog': bool(sample_safety.get('writes_catalog')),
            'production_loop_side_effect': bool(sample_safety.get('production_loop_side_effect')),
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    label = str(args.label)
    evidence_scope = str(args.evidence_scope)
    sample_parquet_path = output_dir / f'{label}.sample.parquet'
    sample_proof_path = output_dir / f'{label}.sample.proof.json'
    gate_dir = output_dir / f'{label}.gate'
    bundle_path = output_dir / f'{label}.worker_benchmark.bundle.json'
    preflight_path = Path(args.preflight_path).expanduser() if args.preflight_path else None
    preflight = json.loads(preflight_path.read_text()) if preflight_path else None
    if preflight is not None and preflight.get('verdict') != 'ACCEPT':
        bundle = _blocked_preflight_bundle(
            label=label,
            evidence_scope=evidence_scope,
            output_dir=output_dir,
            preflight=preflight,
            preflight_path=preflight_path,
        )
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({
            'verdict': bundle['verdict'],
            'bundle_path': str(bundle_path),
            'blocked_reason': bundle['blocked_reason'],
            'preflight_path': str(preflight_path),
            'preflight_issues': bundle['preflight_summary']['issues'],
        }, ensure_ascii=False, indent=2))
        return 1

    sample_builder = _load_script_module('build_intraday_operator_benchmark_sample.py', 'build_intraday_operator_benchmark_sample')
    gate_runner = _load_script_module('run_intraday_operator_kernel_benchmark_gate.py', 'run_intraday_operator_kernel_benchmark_gate')

    sample_args = [
        '--input-root',
        _normalize_input_root(str(args.input_root)),
        '--input-format',
        str(args.input_format),
        '--output-parquet',
        str(sample_parquet_path),
        '--proof-output',
        str(sample_proof_path),
    ]
    _append_if(sample_args, '--start', args.start)
    _append_if(sample_args, '--end', args.end)
    _append_if(sample_args, '--dates', args.dates)
    if int(args.row_limit or 0) > 0:
        sample_args.extend(['--row-limit', str(int(args.row_limit))])
    sample_exit = sample_builder.main(sample_args)
    sample_proof = json.loads(sample_proof_path.read_text())
    if sample_exit != 0 or sample_proof.get('verdict') != 'ACCEPT':
        bundle = _blocked_sample_bundle(
            label=label,
            evidence_scope=evidence_scope,
            output_dir=output_dir,
            sample_proof=sample_proof,
            sample_proof_path=sample_proof_path,
            sample_parquet_path=sample_parquet_path,
            preflight=preflight,
            preflight_path=preflight_path,
        )
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({
            'verdict': bundle['verdict'],
            'bundle_path': str(bundle_path),
            'blocked_reason': bundle['blocked_reason'],
            'sample_row_count': bundle['sample_summary']['row_count'],
        }, ensure_ascii=False, indent=2))
        return 1

    gate_args = [
        '--output-dir',
        str(gate_dir),
        '--label',
        label,
        '--input-parquet',
        str(sample_parquet_path),
        '--window',
        str(int(args.window)),
        '--require-real-bounded',
        '--min-row-count',
        str(int(args.min_row_count)),
        '--max-workers',
        str(int(args.max_workers)),
    ]
    if int(args.row_limit or 0) > 0:
        gate_args.extend(['--row-limit', str(int(args.row_limit))])
    if args.include_array_grouped:
        gate_args.append('--include-array-grouped')
    if args.include_process_sharded_array_grouped:
        gate_args.append('--include-process-sharded-array-grouped')
    if args.include_numba_grouped:
        gate_args.append('--include-numba-grouped')
    if args.include_threaded_grouped:
        gate_args.append('--include-threaded-grouped')
    if args.include_terminal_rolling_corr:
        gate_args.append('--include-terminal-rolling-corr')
    if args.include_ema_state:
        gate_args.append('--include-ema-state')
    if args.include_terminal_ema_state:
        gate_args.append('--include-terminal-ema-state')
    if args.include_cpv_operator:
        gate_args.append('--include-cpv-operator')
        gate_args.extend(['--cpv-backend', str(args.cpv_backend)])
    if args.cpv_terminal_only:
        gate_args.append('--cpv-terminal-only')

    gate_exit = gate_runner.main(gate_args)
    gate_bundle_path = gate_dir / f'{label}.bundle.json'
    gate_bundle = json.loads(gate_bundle_path.read_text())
    bundle = _bundle_payload(
        label=label,
        evidence_scope=evidence_scope,
        sample_proof=sample_proof,
        sample_proof_path=sample_proof_path,
        sample_parquet_path=sample_parquet_path,
        gate_bundle=gate_bundle,
        gate_bundle_path=gate_bundle_path,
        output_dir=output_dir,
        preflight=preflight,
        preflight_path=preflight_path,
    )
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({
        'verdict': bundle['verdict'],
        'bundle_path': str(bundle_path),
        'sample_parquet_path': str(sample_parquet_path),
        'sample_row_count': bundle['sample_summary']['row_count'],
        'gate_verdict': bundle['gate_summary']['verdict'],
        'validation_verdict': bundle['gate_summary']['validation_verdict'],
    }, ensure_ascii=False, indent=2))
    return 0 if sample_exit == 0 and gate_exit == 0 and bundle['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
