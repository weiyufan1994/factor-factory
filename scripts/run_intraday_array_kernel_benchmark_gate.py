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
            'production_default_allowed': gate.get('production_default_allowed'),
            'performance_candidates': gate.get('candidates') or [],
            'direct_array_inputs': (profile.get('input') or {}).get('direct_array_inputs'),
            'input_row_count': (profile.get('input') or {}).get('row_count'),
            'input_group_count': (profile.get('input') or {}).get('group_count'),
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
    parser = argparse.ArgumentParser(description='Run direct-array intraday kernel profile plus validator.')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--label', default='intraday_array_kernel')
    parser.add_argument('--groups', type=int, default=1024)
    parser.add_argument('--rows-per-group', type=int, default=240)
    parser.add_argument('--window', type=int, default=20)
    parser.add_argument('--seed', type=int, default=20260617)
    parser.add_argument('--input-parquet')
    parser.add_argument('--row-limit', type=int)
    parser.add_argument('--group-cols', default='trade_date,ts_code')
    parser.add_argument('--order-col', default='hhmmss')
    parser.add_argument('--price-col', default='price')
    parser.add_argument('--volume-col', default='volume')
    parser.add_argument('--amount-col', default='amount')
    parser.add_argument('--include-numba-grouped', action='store_true')
    parser.add_argument('--require-real-bounded', action='store_true')
    parser.add_argument('--min-row-count', type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    profile_path = output_dir / f'{args.label}.profile.json'
    validation_path = output_dir / f'{args.label}.validation.json'
    bundle_path = output_dir / f'{args.label}.bundle.json'

    profiler = _load_script_module('profile_intraday_array_kernels.py', 'profile_intraday_array_kernels')
    validator = _load_script_module('validate_intraday_array_kernel_profile.py', 'validate_intraday_array_kernel_profile')

    profile = profiler.run_profile(
        groups=int(args.groups),
        rows_per_group=int(args.rows_per_group),
        window=int(args.window),
        seed=int(args.seed),
        include_numba_grouped=bool(args.include_numba_grouped),
        input_parquet=args.input_parquet,
        row_limit=args.row_limit,
        group_cols=[col.strip() for col in str(args.group_cols).split(',') if col.strip()],
        order_col=str(args.order_col),
        price_col=str(args.price_col),
        volume_col=str(args.volume_col),
        amount_col=str(args.amount_col),
    )
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    validation = validator.validate_profile(
        profile,
        min_row_count=int(args.min_row_count or 0),
        require_real_bounded=bool(args.require_real_bounded),
    )
    validation['profile_path'] = str(profile_path)
    validation_path.write_text(json.dumps(validation, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    bundle = _bundle_payload(
        profile=profile,
        validation=validation,
        profile_path=profile_path,
        validation_path=validation_path,
    )
    bundle_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if bundle['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
