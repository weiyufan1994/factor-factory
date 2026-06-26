#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _validate_profile(profile: dict[str, Any], *, require_real_bounded: bool, min_row_count: int = 0) -> dict[str, Any]:
    issues: list[str] = []
    gate = profile.get('performance_gate') or {}
    safety = profile.get('safety') or {}
    profiles = profile.get('profiles') or []
    input_meta = profile.get('input') or {}
    input_row_count = int(input_meta.get('row_count') or 0)

    if profile.get('verdict') != 'ACCEPT':
        issues.append('profile_verdict_not_accept')
    if profile.get('comparison_issues'):
        issues.append('comparison_issues_nonempty')
    if gate.get('benchmark_scope') not in {'synthetic_bounded', 'real_bounded_read_only'}:
        issues.append('unsupported_benchmark_scope')
    if require_real_bounded and gate.get('benchmark_scope') != 'real_bounded_read_only':
        issues.append('benchmark_scope_not_real_bounded')
    if int(min_row_count) > 0 and input_row_count < int(min_row_count):
        issues.append('input_row_count_below_minimum')
    if gate.get('production_default_allowed') is not False:
        issues.append('production_default_allowed_must_be_false_for_pre_wiring_profiles')
    for key in ['starts_backfill', 'writes_datamart', 'production_loop_side_effect']:
        if safety.get(key) is not False:
            issues.append(f'safety_{key}_must_be_false')
    if gate.get('benchmark_scope') == 'real_bounded_read_only' and safety.get('uses_real_market_data') is not True:
        issues.append('real_bounded_profile_must_mark_uses_real_market_data')
    if not isinstance(profiles, list) or not profiles:
        issues.append('profiles_missing_or_empty')
    for item in profiles:
        if item.get('verdict') != 'ACCEPT':
            issues.append(f"profile_item_not_accept:{item.get('operator_id')}:{item.get('backend')}")
        if not item.get('result_hash'):
            issues.append(f"profile_item_missing_result_hash:{item.get('operator_id')}:{item.get('backend')}")

    candidates = gate.get('candidates') or []
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
        'default_replacement_verdict': gate.get('default_replacement_verdict'),
        'promotion_candidate_count': len(promotion_candidates),
        'profile_count': len(profiles) if isinstance(profiles, list) else 0,
        'input_row_count': input_row_count,
        'min_row_count': int(min_row_count),
        'safety': {
            'uses_real_market_data': safety.get('uses_real_market_data'),
            'starts_backfill': safety.get('starts_backfill'),
            'writes_datamart': safety.get('writes_datamart'),
            'production_loop_side_effect': safety.get('production_loop_side_effect'),
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Validate an intraday operator kernel profile before any backend wiring.')
    parser.add_argument('--profile-path', required=True)
    parser.add_argument('--output-path', required=True)
    parser.add_argument('--require-real-bounded', action='store_true')
    parser.add_argument('--min-row-count', type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    profile_path = Path(args.profile_path)
    profile = json.loads(profile_path.read_text())
    payload = _validate_profile(
        profile,
        require_real_bounded=bool(args.require_real_bounded),
        min_row_count=int(args.min_row_count or 0),
    )
    payload['profile_path'] = str(profile_path)
    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    return 0 if payload['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
