#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Validate a safe worker-side moneyflow_slow_state_v1 benchmark bundle.')
    parser.add_argument('--bundle-path', required=True)
    parser.add_argument('--output-path', required=True)
    parser.add_argument('--min-row-count', type=int, default=100000)
    parser.add_argument('--evidence-scope', choices=['bounded_worker', 'production_scale', 'full_is'], default='bounded_worker')
    parser.add_argument('--min-date-count', type=int, default=1)
    parser.add_argument('--required-start')
    parser.add_argument('--required-end')
    return parser.parse_args(argv)


def _load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    candidate = Path(path)
    if not candidate.exists():
        return {}
    return json.loads(candidate.read_text(encoding='utf-8'))


def _check_no_side_effects(prefix: str, safety: dict[str, Any], issues: list[str], *, require_read_only_input: bool) -> None:
    if require_read_only_input and safety.get('read_only_input') is not True:
        issues.append(f'{prefix}_read_only_input_must_be_true')
    for key in ['starts_backfill', 'writes_datamart', 'writes_catalog', 'production_loop_side_effect']:
        if safety.get(key) is not False:
            issues.append(f'{prefix}_{key}_must_be_false')


def _normalize_date(value: Any) -> str:
    return ''.join(ch for ch in str(value or '') if ch.isdigit())[:8]


def _date_bounds(*payloads: dict[str, Any]) -> tuple[str, str, int]:
    dates: list[str] = []
    for payload in payloads:
        for key in ['min_trade_date', 'max_trade_date', 'output_min_trade_date', 'output_max_trade_date', 'start', 'end']:
            value = _normalize_date(payload.get(key))
            if len(value) == 8:
                dates.append(value)
        for key in ['dates', 'trade_dates']:
            raw = payload.get(key) or []
            if isinstance(raw, str):
                raw = raw.split(',')
            for item in raw:
                value = _normalize_date(item)
                if len(value) == 8:
                    dates.append(value)
        coverage = payload.get('coverage_by_date') or {}
        if isinstance(coverage, dict):
            for item in coverage:
                value = _normalize_date(item)
                if len(value) == 8:
                    dates.append(value)
    if not dates:
        return '', '', 0
    unique_dates = sorted(set(dates))
    return unique_dates[0], unique_dates[-1], len(unique_dates)


def validate_payload(
    *,
    safe_bundle: dict[str, Any],
    bundle_path: Path,
    min_row_count: int,
    evidence_scope: str = 'bounded_worker',
    min_date_count: int = 1,
    required_start: str | None = None,
    required_end: str | None = None,
) -> dict[str, Any]:
    issues: list[str] = []
    preflight_path = safe_bundle.get('preflight_path')
    preflight = _load_json(preflight_path)
    worker_bundle_path = safe_bundle.get('worker_benchmark_bundle_path')
    worker_bundle = _load_json(worker_bundle_path)
    sample_proof = _load_json(worker_bundle.get('sample_proof_path') if worker_bundle else None)
    gate_bundle = _load_json(worker_bundle.get('gate_bundle_path') if worker_bundle else None)
    gate_profile = _load_json(gate_bundle.get('profile_path') if gate_bundle else None)
    gate_validation = _load_json(gate_bundle.get('validation_path') if gate_bundle else None)

    preflight_summary = safe_bundle.get('preflight_summary') or {}
    worker_summary = safe_bundle.get('worker_benchmark_summary') or {}
    worker_gate_summary = worker_bundle.get('gate_summary') or {}
    gate_profile_summary = gate_bundle.get('profile_summary') or {}
    gate_validation_summary = gate_bundle.get('validation_summary') or {}

    if safe_bundle.get('verdict') != 'ACCEPT':
        issues.append('safe_bundle_verdict_not_accept')
    if not preflight:
        issues.append('preflight_missing_or_unreadable')
    elif preflight.get('verdict') != 'ACCEPT':
        issues.append('preflight_verdict_not_accept')
    if preflight_summary.get('verdict') != 'ACCEPT':
        issues.append('preflight_summary_verdict_not_accept')
    if not worker_bundle:
        issues.append('worker_bundle_missing_or_unreadable')
    elif worker_bundle.get('verdict') != 'ACCEPT':
        issues.append('worker_bundle_verdict_not_accept')
    if worker_summary.get('verdict') != 'ACCEPT':
        issues.append('safe_worker_summary_verdict_not_accept')
    if not sample_proof:
        issues.append('sample_proof_missing_or_unreadable')
    elif sample_proof.get('verdict') != 'ACCEPT':
        issues.append('sample_proof_verdict_not_accept')
    if not gate_bundle:
        issues.append('gate_bundle_missing_or_unreadable')
    elif gate_bundle.get('verdict') != 'ACCEPT':
        issues.append('gate_bundle_verdict_not_accept')
    if not gate_profile:
        issues.append('gate_profile_missing_or_unreadable')
    elif gate_profile.get('verdict') != 'ACCEPT':
        issues.append('gate_profile_verdict_not_accept')
    if not gate_validation:
        issues.append('gate_validation_missing_or_unreadable')
    elif gate_validation.get('verdict') != 'ACCEPT':
        issues.append('gate_validation_verdict_not_accept')
    if gate_validation_summary and gate_validation_summary.get('verdict') != 'ACCEPT':
        issues.append('gate_validation_summary_verdict_not_accept')

    duplicate_count = sample_proof.get('duplicate_key_count', (worker_bundle.get('sample_summary') or {}).get('duplicate_key_count'))
    if duplicate_count not in {0, 0.0}:
        issues.append('sample_duplicate_key_count_must_be_zero')

    benchmark_scope = (
        gate_validation.get('benchmark_scope')
        or worker_summary.get('benchmark_scope')
        or worker_gate_summary.get('benchmark_scope')
        or gate_profile_summary.get('benchmark_scope')
        or gate_profile.get('benchmark_scope')
    )
    if benchmark_scope != 'real_bounded_read_only':
        issues.append('benchmark_scope_not_real_bounded_read_only')

    production_default_allowed = (
        gate_validation.get('production_default_allowed')
        if 'production_default_allowed' in gate_validation
        else worker_gate_summary.get('production_default_allowed', gate_profile_summary.get('production_default_allowed', gate_profile.get('production_default_allowed')))
    )
    if production_default_allowed is not False:
        issues.append('production_default_allowed_must_be_false')

    input_row_count = int(
        gate_validation.get('input_row_count')
        or sample_proof.get('row_count')
        or (worker_bundle.get('sample_summary') or {}).get('row_count')
        or worker_summary.get('sample_row_count')
        or 0
    )
    summary_row_count = int(worker_summary.get('sample_row_count') or 0)
    if input_row_count < int(min_row_count):
        issues.append('input_row_count_below_minimum')
    if summary_row_count < int(min_row_count):
        issues.append('safe_summary_sample_row_count_below_minimum')
    min_trade_date, max_trade_date, observed_date_count = _date_bounds(
        sample_proof,
        worker_bundle.get('sample_summary') or {},
        worker_summary,
        gate_profile.get('input') or {},
        gate_validation,
    )
    sample_date_count = int(
        sample_proof.get('date_count')
        or (worker_bundle.get('sample_summary') or {}).get('date_count')
        or worker_summary.get('date_count')
        or observed_date_count
        or 0
    )
    if sample_date_count < int(min_date_count):
        issues.append('date_count_below_minimum')
    normalized_required_start = _normalize_date(required_start)
    normalized_required_end = _normalize_date(required_end)
    if normalized_required_start and (not min_trade_date or min_trade_date > normalized_required_start):
        issues.append('required_start_not_covered')
    if normalized_required_end and (not max_trade_date or max_trade_date < normalized_required_end):
        issues.append('required_end_not_covered')
    if evidence_scope in {'production_scale', 'full_is'} and int(min_row_count) < 100000:
        issues.append('production_evidence_min_row_count_too_low')
    if evidence_scope == 'full_is' and (not normalized_required_start or not normalized_required_end):
        issues.append('full_is_requires_required_start_and_end')

    if gate_profile.get('dataset_id') not in {None, 'moneyflow_slow_state_v1'}:
        issues.append('gate_profile_dataset_id_not_moneyflow_slow_state_v1')
    if gate_profile.get('source_dataset') not in {None, 'intraday_flow_distribution_moments_v1'}:
        issues.append('gate_profile_source_dataset_not_intraday_flow_distribution_moments_v1')

    operator_replacement_verdict = (
        gate_validation.get('operator_replacement_verdict')
        or worker_summary.get('operator_replacement_verdict')
        or worker_gate_summary.get('operator_replacement_verdict')
        or gate_profile_summary.get('operator_replacement_verdict')
        or gate_profile.get('operator_replacement_verdict')
    )
    if operator_replacement_verdict == 'BLOCK':
        issues.append('operator_replacement_verdict_block')

    _check_no_side_effects('safe_safety', safe_bundle.get('safety') or {}, issues, require_read_only_input=True)
    _check_no_side_effects('worker_safety', worker_bundle.get('safety') or {}, issues, require_read_only_input=True)
    _check_no_side_effects('sample_safety', sample_proof.get('safety') or {}, issues, require_read_only_input=True)
    gate_safety = gate_bundle.get('safety') or {}
    if gate_safety.get('uses_real_market_data') is not True:
        issues.append('gate_safety_uses_real_market_data_must_be_true')
    for key in ['starts_backfill', 'writes_datamart', 'writes_catalog', 'production_loop_side_effect']:
        if gate_safety.get(key) is not False:
            issues.append(f'gate_safety_{key}_must_be_false')
    profile_safety = gate_profile.get('safety') or {}
    if profile_safety.get('uses_real_market_data') is not True:
        issues.append('profile_safety_uses_real_market_data_must_be_true')
    for key in ['starts_backfill', 'writes_datamart', 'writes_catalog', 'production_loop_side_effect']:
        if profile_safety.get(key) is not False:
            issues.append(f'profile_safety_{key}_must_be_false')

    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'issues': issues,
        'bundle_path': str(bundle_path),
        'preflight_path': str(preflight_path or ''),
        'worker_benchmark_bundle_path': str(worker_bundle_path or ''),
        'sample_proof_path': str(worker_bundle.get('sample_proof_path') or '') if worker_bundle else '',
        'gate_bundle_path': str(worker_bundle.get('gate_bundle_path') or '') if worker_bundle else '',
        'input_row_count': input_row_count,
        'safe_summary_sample_row_count': summary_row_count,
        'min_row_count': int(min_row_count),
        'date_count': sample_date_count,
        'min_date_count': int(min_date_count),
        'min_trade_date': min_trade_date,
        'max_trade_date': max_trade_date,
        'required_start': normalized_required_start,
        'required_end': normalized_required_end,
        'evidence_scope': evidence_scope,
        'benchmark_scope': benchmark_scope,
        'production_default_allowed': production_default_allowed,
        'operator_replacement_verdict': operator_replacement_verdict,
        'safety': {
            'read_only_input': (safe_bundle.get('safety') or {}).get('read_only_input') is True,
            'starts_backfill': bool((safe_bundle.get('safety') or {}).get('starts_backfill')),
            'writes_datamart': bool((safe_bundle.get('safety') or {}).get('writes_datamart')),
            'writes_catalog': bool((safe_bundle.get('safety') or {}).get('writes_catalog')),
            'production_loop_side_effect': bool((safe_bundle.get('safety') or {}).get('production_loop_side_effect')),
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    bundle_path = Path(args.bundle_path).expanduser()
    safe_bundle = json.loads(bundle_path.read_text(encoding='utf-8'))
    payload = validate_payload(
        safe_bundle=safe_bundle,
        bundle_path=bundle_path,
        min_row_count=int(args.min_row_count),
        evidence_scope=str(args.evidence_scope),
        min_date_count=int(args.min_date_count),
        required_start=args.required_start,
        required_end=args.required_end,
    )
    output_path = Path(args.output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if payload['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
