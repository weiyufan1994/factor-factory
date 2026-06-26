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
    gate = profile.get('performance_gate') or {}
    safety = profile.get('safety') or {}
    verdict = 'ACCEPT' if profile.get('verdict') == 'ACCEPT' and validation.get('verdict') == 'ACCEPT' else 'BLOCK'
    return {
        'verdict': verdict,
        'profile_path': str(profile_path),
        'validation_path': str(validation_path),
        'profile_summary': {
            'verdict': profile.get('verdict'),
            'profile_count': profile.get('profile_count'),
            'benchmark_scope': gate.get('benchmark_scope'),
            'default_replacement_verdict': gate.get('default_replacement_verdict'),
            'production_default_allowed': gate.get('production_default_allowed'),
            'performance_candidates': gate.get('candidates') or [],
            'terminal_rolling_corr_summary': profile.get('terminal_rolling_corr_summary'),
        },
        'validation_summary': {
            'verdict': validation.get('verdict'),
            'issue_count': validation.get('issue_count'),
            'issues': validation.get('issues') or [],
            'promotion_candidate_count': validation.get('promotion_candidate_count'),
        },
        'safety': {
            'uses_real_market_data': safety.get('uses_real_market_data'),
            'starts_backfill': safety.get('starts_backfill'),
            'writes_datamart': safety.get('writes_datamart'),
            'production_loop_side_effect': safety.get('production_loop_side_effect'),
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run profile plus validator for intraday operator kernel backend candidates.')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--label', default='intraday_operator_kernel')
    parser.add_argument('--groups', type=int, default=64)
    parser.add_argument('--rows-per-group', type=int, default=240)
    parser.add_argument('--window', type=int, default=20)
    parser.add_argument('--seed', type=int, default=20260616)
    parser.add_argument('--input-parquet')
    parser.add_argument('--row-limit', type=int)
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
    parser.add_argument('--require-real-bounded', action='store_true')
    parser.add_argument('--min-row-count', type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    profile_path = output_dir / f'{args.label}.profile.json'
    validation_path = output_dir / f'{args.label}.validation.json'
    bundle_path = output_dir / f'{args.label}.bundle.json'

    profiler = _load_script_module('profile_intraday_operator_kernels.py', 'profile_intraday_operator_kernels')
    validator = _load_script_module('validate_intraday_operator_kernel_profile.py', 'validate_intraday_operator_kernel_profile')

    profile = profiler.run_profile(
        groups=args.groups,
        rows_per_group=args.rows_per_group,
        window=args.window,
        include_array_grouped=bool(args.include_array_grouped),
        include_process_sharded_array_grouped=bool(args.include_process_sharded_array_grouped),
        include_cpv_operator=bool(args.include_cpv_operator),
        cpv_backend=str(args.cpv_backend),
        cpv_terminal_only=bool(args.cpv_terminal_only),
        include_numba_grouped=bool(args.include_numba_grouped),
        include_threaded_grouped=bool(args.include_threaded_grouped),
        include_terminal_rolling_corr=bool(args.include_terminal_rolling_corr),
        include_ema_state=bool(args.include_ema_state),
        include_terminal_ema_state=bool(args.include_terminal_ema_state),
        max_workers=args.max_workers,
        seed=args.seed,
        input_parquet=args.input_parquet,
        row_limit=args.row_limit,
    )
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + '\n')

    validation = validator._validate_profile(
        profile,
        require_real_bounded=bool(args.require_real_bounded),
        min_row_count=int(args.min_row_count or 0),
    )
    validation['profile_path'] = str(profile_path)
    validation_path.write_text(json.dumps(validation, ensure_ascii=False, indent=2) + '\n')

    bundle = _bundle_payload(profile=profile, validation=validation, profile_path=profile_path, validation_path=validation_path)
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n')
    return 0 if bundle['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
