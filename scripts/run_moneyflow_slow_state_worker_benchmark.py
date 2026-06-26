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
    parser = argparse.ArgumentParser(description='Build a bounded slow-state input sample and run the read-only moneyflow slow-state benchmark gate.')
    parser.add_argument('--input-root', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--label', default='moneyflow_slow_state_worker_benchmark')
    parser.add_argument('--start')
    parser.add_argument('--end')
    parser.add_argument('--dates')
    parser.add_argument('--row-limit', type=int, default=0)
    parser.add_argument('--cutoff-times', default='14:50:00')
    parser.add_argument('--lambdas', default='0.70,0.85,0.93')
    parser.add_argument('--operator-backends', default='reference,array_grouped,process_sharded_array_grouped')
    parser.add_argument('--min-speedup-ratio', type=float, default=1.10)
    parser.add_argument('--max-workers', type=int, default=1)
    parser.add_argument('--min-row-count', type=int, default=100000)
    return parser.parse_args(argv)


def _append_if(args: list[str], flag: str, value: str | None) -> None:
    if value:
        args.extend([flag, value])


def _normalize_input_root(value: str) -> str:
    return value.rstrip('/') if value.startswith('s3://') else str(Path(value).expanduser())


def _bundle_payload(
    *,
    label: str,
    output_dir: Path,
    sample_parquet_path: Path,
    sample_proof_path: Path,
    sample_proof: dict[str, Any],
    gate_bundle_path: Path | None,
    gate_bundle: dict[str, Any] | None,
    blocked_reason: str | None = None,
) -> dict[str, Any]:
    sample_safety = sample_proof.get('safety') or {}
    gate_bundle = gate_bundle or {}
    gate_profile = gate_bundle.get('profile_summary') or {}
    gate_validation = gate_bundle.get('validation_summary') or {}
    gate_safety = gate_bundle.get('safety') or {}
    sample_ok = sample_proof.get('verdict') == 'ACCEPT'
    gate_ok = gate_bundle.get('verdict') == 'ACCEPT' if gate_bundle else False
    return {
        'verdict': 'ACCEPT' if sample_ok and gate_ok else 'BLOCK',
        'label': label,
        'output_dir': str(output_dir),
        'blocked_reason': blocked_reason,
        'sample_parquet_path': str(sample_parquet_path),
        'sample_proof_path': str(sample_proof_path),
        'gate_bundle_path': str(gate_bundle_path) if gate_bundle_path else None,
        'gate_profile_path': gate_bundle.get('profile_path'),
        'gate_validation_path': gate_bundle.get('validation_path'),
        'sample_summary': {
            'verdict': sample_proof.get('verdict'),
            'row_count': sample_proof.get('row_count'),
            'date_count': sample_proof.get('date_count'),
            'ticker_count': sample_proof.get('ticker_count'),
            'duplicate_key_count': sample_proof.get('duplicate_key_count'),
            'semantic_scope': sample_proof.get('semantic_scope'),
        },
        'gate_summary': {
            'verdict': gate_bundle.get('verdict'),
            'profile_verdict': gate_profile.get('verdict'),
            'validation_verdict': gate_validation.get('verdict'),
            'validation_issues': gate_validation.get('issues') or [],
            'benchmark_scope': gate_profile.get('benchmark_scope'),
            'operator_replacement_verdict': gate_profile.get('operator_replacement_verdict'),
            'production_default_allowed': gate_profile.get('production_default_allowed'),
            'best_profile_id': gate_profile.get('best_profile_id'),
            'best_speedup_vs_reference': gate_profile.get('best_speedup_vs_reference'),
        },
        'safety': {
            'read_only_input': sample_safety.get('read_only_input') is True,
            'starts_backfill': bool(sample_safety.get('starts_backfill') or gate_safety.get('starts_backfill')),
            'writes_datamart': bool(sample_safety.get('writes_datamart') or gate_safety.get('writes_datamart')),
            'writes_catalog': bool(sample_safety.get('writes_catalog') or gate_safety.get('writes_catalog')),
            'production_loop_side_effect': bool(
                sample_safety.get('production_loop_side_effect') or gate_safety.get('production_loop_side_effect')
            ),
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    label = str(args.label)
    sample_parquet_path = output_dir / f'{label}.sample.parquet'
    sample_proof_path = output_dir / f'{label}.sample.proof.json'
    gate_dir = output_dir / f'{label}.gate'
    gate_bundle_path = gate_dir / f'{label}.bundle.json'
    bundle_path = output_dir / f'{label}.worker_benchmark.bundle.json'

    sample_builder = _load_script_module('build_moneyflow_slow_state_benchmark_sample.py', 'build_moneyflow_slow_state_benchmark_sample')
    gate_runner = _load_script_module('run_moneyflow_slow_state_operator_benchmark_gate.py', 'run_moneyflow_slow_state_operator_benchmark_gate')

    sample_args = [
        '--input-root',
        _normalize_input_root(str(args.input_root)),
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
    sample_proof = json.loads(sample_proof_path.read_text(encoding='utf-8'))
    if sample_exit != 0 or sample_proof.get('verdict') != 'ACCEPT':
        bundle = _bundle_payload(
            label=label,
            output_dir=output_dir,
            sample_parquet_path=sample_parquet_path,
            sample_proof_path=sample_proof_path,
            sample_proof=sample_proof,
            gate_bundle_path=None,
            gate_bundle=None,
            blocked_reason='sample_builder_not_accept',
        )
        bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return 1

    gate_args = [
        '--output-dir',
        str(gate_dir),
        '--label',
        label,
        '--input-parquet',
        str(sample_parquet_path),
        '--cutoff-times',
        str(args.cutoff_times),
        '--lambdas',
        str(args.lambdas),
        '--operator-backends',
        str(args.operator_backends),
        '--min-speedup-ratio',
        str(float(args.min_speedup_ratio)),
        '--max-workers',
        str(int(args.max_workers)),
        '--require-real-bounded',
        '--min-row-count',
        str(int(args.min_row_count)),
    ]
    gate_exit = gate_runner.main(gate_args)
    gate_bundle = json.loads(gate_bundle_path.read_text(encoding='utf-8'))
    bundle = _bundle_payload(
        label=label,
        output_dir=output_dir,
        sample_parquet_path=sample_parquet_path,
        sample_proof_path=sample_proof_path,
        sample_proof=sample_proof,
        gate_bundle_path=gate_bundle_path,
        gate_bundle=gate_bundle,
        blocked_reason=None if gate_exit == 0 and gate_bundle.get('verdict') == 'ACCEPT' else 'gate_not_accept',
    )
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if gate_exit == 0 and bundle['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
