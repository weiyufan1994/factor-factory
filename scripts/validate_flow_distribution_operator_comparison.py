#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = [
    'verdict',
    'date',
    'profile_count',
    'profiles',
    'best_profile_id',
    'prepared_vs_raw_total_speedup',
    'best_speedup_vs_raw_vectorized',
    'min_speedup_ratio',
    'baseline_profile_id',
    'baseline_profile_accept',
    'accepted_profile_row_count_equal',
    'accepted_profile_duplicate_key_count_zero',
    'accepted_profile_key_hash_equal',
    'operator_replacement_verdict',
    'operator_replacement_issues',
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Validate a bounded flow-distribution operator comparison proof.')
    parser.add_argument('--proof-path', required=True)
    parser.add_argument('--output-path', required=True)
    return parser.parse_args()


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _is_non_negative_number(value: Any) -> bool:
    return isinstance(value, int | float) and value >= 0


def validate_payload(payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in payload:
            issues.append(f'missing_required_field:{field}')
    if issues:
        return issues

    if payload.get('verdict') != 'ACCEPT':
        issues.append('comparison_verdict_not_accept')
    if payload.get('operator_replacement_verdict') != 'ACCEPT':
        issues.append('operator_replacement_verdict_not_accept')
    if payload.get('baseline_profile_id') != 'raw:vectorized':
        issues.append('baseline_profile_id_not_raw_vectorized')
    if payload.get('baseline_profile_accept') is not True:
        issues.append('baseline_profile_not_accept')
    for field in [
        'accepted_profile_row_count_equal',
        'accepted_profile_duplicate_key_count_zero',
        'accepted_profile_key_hash_equal',
    ]:
        if not _is_bool(payload.get(field)):
            issues.append(f'{field}_not_bool')
        elif payload.get(field) is not True:
            issues.append(f'{field}_not_true')
    profiles = payload.get('profiles')
    if not isinstance(profiles, list) or not profiles:
        issues.append('profiles_empty_or_not_list')
    else:
        if int(payload.get('profile_count', -1)) != len(profiles):
            issues.append('profile_count_mismatch')
        for index, profile in enumerate(profiles):
            if not isinstance(profile, dict):
                issues.append(f'profile_{index}_not_object')
                continue
            for field in ['profile_id', 'verdict', 'row_count', 'duplicate_key_count', 'output_key_hash', 'stage_seconds']:
                if field not in profile:
                    issues.append(f'profile_{index}_missing_field:{field}')
            if profile.get('verdict') == 'ACCEPT':
                if int(profile.get('duplicate_key_count', -1)) != 0:
                    issues.append(f'profile_{index}_duplicate_key_count_nonzero')
                key_hash = str(profile.get('output_key_hash') or '')
                if len(key_hash) != 64:
                    issues.append(f'profile_{index}_output_key_hash_invalid')
                stage_seconds = profile.get('stage_seconds')
                if not isinstance(stage_seconds, dict) or not _is_non_negative_number(stage_seconds.get('total_seconds')):
                    issues.append(f'profile_{index}_total_seconds_invalid')
    if not _is_non_negative_number(payload.get('prepared_vs_raw_total_speedup')):
        issues.append('prepared_vs_raw_total_speedup_invalid')
    if not _is_non_negative_number(payload.get('best_speedup_vs_raw_vectorized')):
        issues.append('best_speedup_vs_raw_vectorized_invalid')
    if not _is_non_negative_number(payload.get('min_speedup_ratio')):
        issues.append('min_speedup_ratio_invalid')
    if payload.get('operator_replacement_issues') not in ([], None):
        issues.append('operator_replacement_issues_not_empty')
    return issues


def validate_proof_path(proof_path: Path, output_path: Path) -> int:
    payload = json.loads(proof_path.read_text(encoding='utf-8'))
    issues = validate_payload(payload)
    result = {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'proof_path': str(proof_path),
        'issues': issues,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['verdict'] == 'ACCEPT' else 2


def main() -> int:
    args = parse_args()
    return validate_proof_path(Path(args.proof_path).expanduser(), Path(args.output_path).expanduser())


if __name__ == '__main__':
    raise SystemExit(main())
