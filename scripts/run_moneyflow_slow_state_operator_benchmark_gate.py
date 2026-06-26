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


def _bundle_payload(*, profile: dict[str, Any], validation: dict[str, Any], profile_path: Path, validation_path: Path) -> dict[str, Any]:
    safety = profile.get('safety') or {}
    return {
        'verdict': 'ACCEPT' if profile.get('verdict') == 'ACCEPT' and validation.get('verdict') == 'ACCEPT' else 'BLOCK',
        'profile_path': str(profile_path),
        'validation_path': str(validation_path),
        'profile_summary': {
            'verdict': profile.get('verdict'),
            'profile_count': profile.get('profile_count'),
            'benchmark_scope': profile.get('benchmark_scope'),
            'production_default_allowed': profile.get('production_default_allowed'),
            'operator_replacement_verdict': profile.get('operator_replacement_verdict'),
            'operator_replacement_issues': profile.get('operator_replacement_issues') or [],
            'best_profile_id': profile.get('best_profile_id'),
            'best_speedup_vs_reference': profile.get('best_speedup_vs_reference'),
        },
        'validation_summary': {
            'verdict': validation.get('verdict'),
            'issue_count': validation.get('issue_count'),
            'issues': validation.get('issues') or [],
            'operator_replacement_verdict': validation.get('operator_replacement_verdict'),
        },
        'safety': {
            'uses_real_market_data': safety.get('uses_real_market_data'),
            'starts_backfill': safety.get('starts_backfill'),
            'writes_datamart': safety.get('writes_datamart'),
            'writes_catalog': safety.get('writes_catalog'),
            'production_loop_side_effect': safety.get('production_loop_side_effect'),
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run profile plus validator for moneyflow_slow_state_v1 operator candidates.')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--label', default='moneyflow_slow_state_operator')
    parser.add_argument('--input-parquet')
    parser.add_argument('--row-limit', type=int, default=0)
    parser.add_argument('--tickers', type=int, default=128)
    parser.add_argument('--dates', type=int, default=240)
    parser.add_argument('--cutoff-times', default='14:50:00')
    parser.add_argument('--lambdas', default='0.70,0.85,0.93')
    parser.add_argument('--operator-backends', default='reference,array_grouped,process_sharded_array_grouped')
    parser.add_argument('--min-speedup-ratio', type=float, default=1.10)
    parser.add_argument('--max-workers', type=int, default=1)
    parser.add_argument('--seed', type=int, default=20260617)
    parser.add_argument('--require-real-bounded', action='store_true')
    parser.add_argument('--min-row-count', type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    label = str(args.label)
    profile_path = output_dir / f'{label}.profile.json'
    validation_path = output_dir / f'{label}.validation.json'
    bundle_path = output_dir / f'{label}.bundle.json'

    profiler = _load_script_module('profile_moneyflow_slow_state_operator.py', 'profile_moneyflow_slow_state_operator')
    validator = _load_script_module('validate_moneyflow_slow_state_operator_profile.py', 'validate_moneyflow_slow_state_operator_profile')

    profile_args = [
        '--output-path',
        str(profile_path),
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
        '--seed',
        str(int(args.seed)),
    ]
    if args.input_parquet:
        profile_args.extend(['--input-parquet', str(Path(args.input_parquet).expanduser())])
    else:
        profile_args.extend(['--tickers', str(int(args.tickers)), '--dates', str(int(args.dates))])
    if int(args.row_limit or 0) > 0:
        profile_args.extend(['--row-limit', str(int(args.row_limit))])

    profile_exit = profiler.main(profile_args)
    profile = json.loads(profile_path.read_text(encoding='utf-8'))

    validation_args = [
        '--profile-path',
        str(profile_path),
        '--output-path',
        str(validation_path),
        '--min-row-count',
        str(int(args.min_row_count or 0)),
    ]
    if args.require_real_bounded:
        validation_args.append('--require-real-bounded')
    validation_exit = validator.main(validation_args)
    validation = json.loads(validation_path.read_text(encoding='utf-8'))

    bundle = _bundle_payload(profile=profile, validation=validation, profile_path=profile_path, validation_path=validation_path)
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if profile_exit == 0 and validation_exit == 0 and bundle['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
