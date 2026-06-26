#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import profile_flow_distribution_moments_operator as profiler  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Compare bounded operator profiles for intraday_flow_distribution_moments_v1.')
    parser.add_argument('--minute-root', required=True)
    parser.add_argument('--prepared-minute-root', required=True)
    parser.add_argument('--date', required=True)
    parser.add_argument('--output-path', required=True)
    parser.add_argument('--cutoff-times', default='10:30:00,11:30:00,14:00:00,14:30:00,14:50:00,14:55:00')
    parser.add_argument('--threshold-lookback-days', default='20,60')
    parser.add_argument('--threshold-quantile', type=float, default=0.75)
    parser.add_argument('--threshold-backend', default='pandas', choices=['pandas', 'polars'])
    parser.add_argument('--min-minutes', type=int, default=20)
    parser.add_argument('--operator-backends', default='vectorized,numba_sorted')
    parser.add_argument('--source-ready-only', action='store_true')
    parser.add_argument('--min-speedup-ratio', type=float, default=1.10)
    return parser.parse_args()


def split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(',') if item.strip()]


def _profile_one(
    *,
    input_kind: str,
    root: Path,
    date: str,
    cutoff_times: str,
    threshold_lookback_days: str,
    threshold_quantile: float,
    threshold_backend: str,
    min_minutes: int,
    operator_backend: str,
    source_ready_only: bool,
) -> dict[str, object]:
    argv = [
        'profile_flow_distribution_moments_operator.py',
        '--date',
        date,
        '--output-path',
        str(Path('/tmp') / 'factorforge_operator_profile_unused.json'),
        '--cutoff-times',
        cutoff_times,
        '--threshold-lookback-days',
        threshold_lookback_days,
        '--threshold-quantile',
        str(threshold_quantile),
        '--threshold-backend',
        threshold_backend,
        '--min-minutes',
        str(min_minutes),
        '--operator-backend',
        operator_backend,
    ]
    if input_kind == 'raw':
        argv.extend(['--minute-root', str(root)])
    else:
        argv.extend(['--prepared-minute-root', str(root)])
    if source_ready_only:
        argv.append('--source-ready-only')

    old_argv = sys.argv[:]
    old_write_payload = profiler._write_payload
    captured: dict[str, object] = {}

    def capture_payload(_output_path: Path, payload: dict[str, object]) -> None:
        captured.update(payload)

    try:
        sys.argv = argv
        profiler._write_payload = capture_payload
        profiler.main()
    finally:
        sys.argv = old_argv
        profiler._write_payload = old_write_payload

    captured['profile_id'] = f'{input_kind}:{operator_backend}'
    return captured


def _speedup(baseline: float, candidate: float) -> float:
    return float(baseline) / float(candidate) if baseline > 0.0 and candidate > 0.0 else 0.0


def _summarize_profiles(profiles: list[dict[str, object]], *, min_speedup_ratio: float) -> dict[str, object]:
    accepted = [item for item in profiles if item.get('verdict') == 'ACCEPT']
    best = min(
        accepted,
        key=lambda item: float(item.get('stage_seconds', {}).get('total_seconds', float('inf'))),
    ) if accepted else {}
    raw_vectorized = next((item for item in profiles if item.get('profile_id') == 'raw:vectorized'), {})
    prepared_vectorized = next((item for item in profiles if item.get('profile_id') == 'prepared:vectorized'), {})
    baseline_profile_id = 'raw:vectorized'
    baseline_profile_accept = bool(raw_vectorized) and raw_vectorized.get('verdict') == 'ACCEPT'
    raw_total = float(raw_vectorized.get('stage_seconds', {}).get('total_seconds', 0.0)) if raw_vectorized else 0.0
    prepared_total = float(prepared_vectorized.get('stage_seconds', {}).get('total_seconds', 0.0)) if prepared_vectorized else 0.0
    prepared_vs_raw_speedup = _speedup(raw_total, prepared_total)
    best_speedup = _speedup(raw_total, float(best.get('stage_seconds', {}).get('total_seconds', 0.0))) if best else 0.0
    accepted_row_counts = {int(item.get('row_count', -1)) for item in accepted}
    accepted_profile_row_count_equal = bool(accepted) and len(accepted_row_counts) == 1
    accepted_profile_duplicate_key_count_zero = bool(accepted) and all(int(item.get('duplicate_key_count', -1)) == 0 for item in accepted)
    accepted_key_hashes = {str(item.get('output_key_hash') or '') for item in accepted}
    accepted_profile_key_hash_equal = bool(accepted) and len(accepted_key_hashes) == 1 and '' not in accepted_key_hashes
    issues: list[str] = []
    if not profiles or not accepted:
        issues.append('no_accepted_profiles')
    if not baseline_profile_accept:
        issues.append('baseline_profile_not_accept')
    if best_speedup < float(min_speedup_ratio):
        issues.append('best_profile_not_materially_faster_than_raw_vectorized')
    if not accepted_profile_row_count_equal:
        issues.append('accepted_profile_row_count_mismatch')
    if not accepted_profile_duplicate_key_count_zero:
        issues.append('accepted_profile_duplicate_keys')
    if not accepted_profile_key_hash_equal:
        issues.append('accepted_profile_key_hash_mismatch')
    return {
        'best_profile_id': str(best.get('profile_id') or ''),
        'best_profile_total_seconds': float(best.get('stage_seconds', {}).get('total_seconds', 0.0)) if best else 0.0,
        'raw_vectorized_total_seconds': raw_total,
        'prepared_vectorized_total_seconds': prepared_total,
        'prepared_vs_raw_total_speedup': prepared_vs_raw_speedup,
        'best_speedup_vs_raw_vectorized': best_speedup,
        'min_speedup_ratio': float(min_speedup_ratio),
        'baseline_profile_id': baseline_profile_id,
        'baseline_profile_accept': baseline_profile_accept,
        'accepted_profile_row_count_equal': accepted_profile_row_count_equal,
        'accepted_profile_duplicate_key_count_zero': accepted_profile_duplicate_key_count_zero,
        'accepted_profile_key_hash_equal': accepted_profile_key_hash_equal,
        'operator_replacement_verdict': 'ACCEPT' if not issues else 'BLOCK',
        'operator_replacement_issues': issues,
    }


def main() -> int:
    args = parse_args()
    profiles: list[dict[str, object]] = []
    for backend in split_csv(args.operator_backends):
        profiles.append(_profile_one(
            input_kind='raw',
            root=Path(args.minute_root).expanduser(),
            date=args.date,
            cutoff_times=args.cutoff_times,
            threshold_lookback_days=args.threshold_lookback_days,
            threshold_quantile=args.threshold_quantile,
            threshold_backend=args.threshold_backend,
            min_minutes=args.min_minutes,
            operator_backend=backend,
            source_ready_only=args.source_ready_only,
        ))
        profiles.append(_profile_one(
            input_kind='prepared',
            root=Path(args.prepared_minute_root).expanduser(),
            date=args.date,
            cutoff_times=args.cutoff_times,
            threshold_lookback_days=args.threshold_lookback_days,
            threshold_quantile=args.threshold_quantile,
            threshold_backend=args.threshold_backend,
            min_minutes=args.min_minutes,
            operator_backend=backend,
            source_ready_only=args.source_ready_only,
        ))

    summary = _summarize_profiles(profiles, min_speedup_ratio=float(args.min_speedup_ratio))
    payload = {
        'verdict': 'ACCEPT' if profiles and not any(item.get('verdict') == 'BLOCK' for item in profiles) else 'BLOCK',
        'date': args.date,
        'profile_count': len(profiles),
        'profiles': profiles,
        **summary,
        'generated_at_unix': float(time.time()),
    }
    output_path = Path(args.output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload['verdict'] == 'ACCEPT' else 2


if __name__ == '__main__':
    raise SystemExit(main())
