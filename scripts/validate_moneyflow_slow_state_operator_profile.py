#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _validate_profile(payload: dict[str, Any], *, require_real_bounded: bool, min_row_count: int = 0) -> dict[str, Any]:
    issues: list[str] = []
    input_meta = payload.get('input') or {}
    safety = payload.get('safety') or {}
    profiles = payload.get('profiles') or []
    benchmark_scope = payload.get('benchmark_scope')
    input_row_count = int(input_meta.get('row_count') or 0)

    if payload.get('verdict') != 'ACCEPT':
        issues.append('profile_verdict_not_accept')
    if payload.get('dataset_id') != 'moneyflow_slow_state_v1':
        issues.append('dataset_id_not_moneyflow_slow_state_v1')
    if payload.get('source_dataset') != 'intraday_flow_distribution_moments_v1':
        issues.append('source_dataset_not_intraday_flow_distribution_moments_v1')
    if benchmark_scope not in {'synthetic_bounded', 'real_bounded_read_only'}:
        issues.append('unsupported_benchmark_scope')
    if require_real_bounded and benchmark_scope != 'real_bounded_read_only':
        issues.append('benchmark_scope_not_real_bounded')
    if require_real_bounded and safety.get('uses_real_market_data') is not True:
        issues.append('real_bounded_profile_must_mark_uses_real_market_data')
    if int(min_row_count) > 0 and input_row_count < int(min_row_count):
        issues.append('input_row_count_below_minimum')
    if payload.get('production_default_allowed') is not False:
        issues.append('production_default_allowed_must_be_false_for_pre_wiring_profiles')
    for key in ['starts_backfill', 'writes_datamart', 'writes_catalog', 'production_loop_side_effect']:
        if safety.get(key) is not False:
            issues.append(f'safety_{key}_must_be_false')

    if not isinstance(profiles, list) or not profiles:
        issues.append('profiles_missing_or_empty')
    elif int(payload.get('profile_count') or -1) != len(profiles):
        issues.append('profile_count_mismatch')
    for index, profile in enumerate(profiles if isinstance(profiles, list) else []):
        if profile.get('verdict') != 'ACCEPT':
            issues.append(f"profile_{index}_verdict_not_accept:{profile.get('profile_id')}")
        if int(profile.get('duplicate_key_count', -1)) != 0:
            issues.append(f"profile_{index}_duplicate_key_count_nonzero:{profile.get('profile_id')}")
        result_hash = str(profile.get('result_hash') or '')
        if len(result_hash) != 64:
            issues.append(f"profile_{index}_result_hash_invalid:{profile.get('profile_id')}")

    checks = [
        ('baseline_profile_accept', 'baseline_profile_not_accept'),
        ('accepted_profile_row_count_equal', 'accepted_profile_row_count_mismatch'),
        ('accepted_profile_duplicate_key_count_zero', 'accepted_profile_duplicate_keys'),
        ('accepted_profile_key_hash_equal', 'accepted_profile_hash_mismatch'),
    ]
    for field, issue in checks:
        if payload.get(field) is not True:
            issues.append(issue)
    if payload.get('baseline_profile_id') != 'reference':
        issues.append('baseline_profile_id_not_reference')
    if payload.get('operator_replacement_verdict') == 'BLOCK':
        issues.append('operator_replacement_verdict_block')

    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'issue_count': len(issues),
        'issues': issues,
        'benchmark_scope': benchmark_scope,
        'production_default_allowed': payload.get('production_default_allowed'),
        'operator_replacement_verdict': payload.get('operator_replacement_verdict'),
        'baseline_profile_id': payload.get('baseline_profile_id'),
        'profile_count': len(profiles) if isinstance(profiles, list) else 0,
        'input_row_count': input_row_count,
        'min_row_count': int(min_row_count),
        'safety': {
            'uses_real_market_data': safety.get('uses_real_market_data'),
            'starts_backfill': safety.get('starts_backfill'),
            'writes_datamart': safety.get('writes_datamart'),
            'writes_catalog': safety.get('writes_catalog'),
            'production_loop_side_effect': safety.get('production_loop_side_effect'),
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Validate a moneyflow_slow_state_v1 bounded operator profile.')
    parser.add_argument('--profile-path', required=True)
    parser.add_argument('--output-path', required=True)
    parser.add_argument('--require-real-bounded', action='store_true')
    parser.add_argument('--min-row-count', type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    profile_path = Path(args.profile_path).expanduser()
    payload = json.loads(profile_path.read_text(encoding='utf-8'))
    result = _validate_profile(
        payload,
        require_real_bounded=bool(args.require_real_bounded),
        min_row_count=int(args.min_row_count or 0),
    )
    result['profile_path'] = str(profile_path)
    output_path = Path(args.output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if result['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
