#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SYNTHETIC_SCOPE = 'synthetic_bounded_direct_array'
REAL_BOUNDED_SCOPE = 'real_bounded_direct_array'
ALLOWED_SCOPES = {SYNTHETIC_SCOPE, REAL_BOUNDED_SCOPE}
EXPECTED_OPERATORS = {
    'rolling_corr_grouped_arrays',
    'terminal_corr_grouped_arrays',
    'occupation_location_grouped_arrays',
}


def validate_profile(profile: dict[str, Any], *, min_row_count: int = 0, require_real_bounded: bool = False) -> dict[str, Any]:
    issues: list[str] = []
    gate = profile.get('performance_gate') or {}
    safety = profile.get('safety') or {}
    input_meta = profile.get('input') or {}
    profiles = profile.get('profiles') or []
    input_row_count = int(input_meta.get('row_count') or 0)

    if profile.get('verdict') != 'ACCEPT':
        issues.append('profile_verdict_not_accept')
    if profile.get('comparison_issues'):
        issues.append('comparison_issues_nonempty')
    benchmark_scope = gate.get('benchmark_scope')
    if benchmark_scope not in ALLOWED_SCOPES:
        issues.append('benchmark_scope_not_supported_direct_array_scope')
    if require_real_bounded and benchmark_scope != REAL_BOUNDED_SCOPE:
        issues.append('benchmark_scope_not_real_bounded_direct_array')
    if gate.get('production_default_allowed') is not False:
        issues.append('production_default_allowed_must_be_false')
    if input_meta.get('direct_array_inputs') is not True:
        issues.append('direct_array_inputs_must_be_true')
    if benchmark_scope == SYNTHETIC_SCOPE and input_meta.get('synthetic') is not True:
        issues.append('input_synthetic_must_be_true')
    if benchmark_scope == REAL_BOUNDED_SCOPE and input_meta.get('synthetic') is not False:
        issues.append('real_bounded_input_synthetic_must_be_false')
    if input_row_count < int(min_row_count):
        issues.append('input_row_count_below_minimum')
    for key in ['starts_backfill', 'writes_datamart', 'production_loop_side_effect']:
        if safety.get(key) is not False:
            issues.append(f'safety_{key}_must_be_false')
    if benchmark_scope == SYNTHETIC_SCOPE and safety.get('uses_real_market_data') is not False:
        issues.append('synthetic_safety_uses_real_market_data_must_be_false')
    if benchmark_scope == REAL_BOUNDED_SCOPE and safety.get('uses_real_market_data') is not True:
        issues.append('real_bounded_safety_uses_real_market_data_must_be_true')
    if not isinstance(profiles, list) or not profiles:
        issues.append('profiles_missing_or_empty')

    operators_seen: set[str] = set()
    reference_seen: set[str] = set()
    candidate_seen: set[str] = set()
    for item in profiles if isinstance(profiles, list) else []:
        operator_id = str(item.get('operator_id') or '')
        backend = str(item.get('backend') or '')
        operators_seen.add(operator_id)
        if item.get('verdict') != 'ACCEPT':
            issues.append(f'profile_item_not_accept:{operator_id}:{backend}')
        if not item.get('result_hash'):
            issues.append(f'profile_item_missing_result_hash:{operator_id}:{backend}')
        if backend == 'reference_loop':
            reference_seen.add(operator_id)
        elif backend:
            candidate_seen.add(operator_id)

    missing_operators = sorted(EXPECTED_OPERATORS - operators_seen)
    if missing_operators:
        issues.append('expected_operator_profiles_missing:' + ','.join(missing_operators))
    missing_reference = sorted(EXPECTED_OPERATORS - reference_seen)
    if missing_reference:
        issues.append('reference_loop_profiles_missing:' + ','.join(missing_reference))
    missing_candidates = sorted(EXPECTED_OPERATORS - candidate_seen)
    if missing_candidates:
        issues.append('candidate_profiles_missing:' + ','.join(missing_candidates))

    candidates = gate.get('candidates') or []
    if not isinstance(candidates, list) or not candidates:
        issues.append('performance_candidates_missing')
        candidates = []
    promotion_candidates = [
        item for item in candidates
        if item.get('performance_verdict') == 'PROMOTE'
    ]

    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'issue_count': len(issues),
        'issues': issues,
        'benchmark_scope': gate.get('benchmark_scope'),
        'production_default_allowed': gate.get('production_default_allowed'),
        'profile_count': len(profiles) if isinstance(profiles, list) else 0,
        'input_row_count': input_row_count,
        'min_row_count': int(min_row_count),
        'direct_array_inputs': input_meta.get('direct_array_inputs'),
        'operator_count': len(operators_seen),
        'promotion_candidate_count': len(promotion_candidates),
        'performance_candidate_count': len(candidates),
        'safety': {
            'uses_real_market_data': safety.get('uses_real_market_data'),
            'starts_backfill': safety.get('starts_backfill'),
            'writes_datamart': safety.get('writes_datamart'),
            'production_loop_side_effect': safety.get('production_loop_side_effect'),
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Validate a bounded direct-array intraday kernel profile.')
    parser.add_argument('--profile-path', required=True)
    parser.add_argument('--output-path', required=True)
    parser.add_argument('--min-row-count', type=int, default=0)
    parser.add_argument('--require-real-bounded', action='store_true')
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    profile_path = Path(args.profile_path).expanduser()
    profile = json.loads(profile_path.read_text(encoding='utf-8'))
    payload = validate_profile(
        profile,
        min_row_count=int(args.min_row_count or 0),
        require_real_bounded=bool(args.require_real_bounded),
    )
    payload['profile_path'] = str(profile_path)
    output_path = Path(args.output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if payload['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
