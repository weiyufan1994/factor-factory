#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

EVIDENCE_SCOPES = {'bounded_worker', 'production_scale', 'full_is'}
PRODUCTION_EVIDENCE_SCOPES = {'production_scale', 'full_is'}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Validate a worker-side intraday operator benchmark bundle.')
    parser.add_argument('--bundle-path', required=True)
    parser.add_argument('--output-path', required=True)
    parser.add_argument('--min-row-count', type=int, default=100000)
    parser.add_argument('--evidence-scope', choices=sorted(EVIDENCE_SCOPES))
    return parser.parse_args(argv)


def _load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    candidate = Path(path)
    if not candidate.exists():
        return {}
    return json.loads(candidate.read_text())


def _flag(value: Any) -> bool:
    return value is True


def _collect_candidates(worker_bundle: dict[str, Any], gate_bundle: dict[str, Any]) -> list[dict[str, Any]]:
    worker_summary = worker_bundle.get('gate_summary') or {}
    gate_profile = gate_bundle.get('profile_summary') or {}
    candidates = worker_summary.get('performance_candidates') or gate_profile.get('performance_candidates') or []
    return candidates if isinstance(candidates, list) else []


def _check_safety(prefix: str, safety: dict[str, Any], issues: list[str], *, require_read_only_input: bool) -> None:
    if require_read_only_input and safety.get('read_only_input') is not True:
        issues.append(f'{prefix}_read_only_input_must_be_true')
    for key in ['starts_backfill', 'writes_datamart', 'writes_catalog', 'production_loop_side_effect']:
        if safety.get(key) is not False:
            issues.append(f'{prefix}_{key}_must_be_false')


def validate_payload(
    *,
    worker_bundle: dict[str, Any],
    worker_bundle_path: Path,
    min_row_count: int,
    evidence_scope: str | None = None,
) -> dict[str, Any]:
    issues: list[str] = []
    sample_proof_path = worker_bundle.get('sample_proof_path')
    gate_bundle_path = worker_bundle.get('gate_bundle_path')
    sample_proof = _load_json(sample_proof_path)
    gate_bundle = _load_json(gate_bundle_path)
    gate_validation_path = gate_bundle.get('validation_path') or worker_bundle.get('gate_validation_path')
    gate_validation = _load_json(gate_validation_path)

    worker_gate_summary = worker_bundle.get('gate_summary') or {}
    gate_profile = gate_bundle.get('profile_summary') or {}
    gate_validation_summary = gate_bundle.get('validation_summary') or {}
    sample_summary = worker_bundle.get('sample_summary') or {}
    resolved_evidence_scope = str(evidence_scope or worker_bundle.get('evidence_scope') or '')
    if resolved_evidence_scope not in EVIDENCE_SCOPES:
        issues.append('evidence_scope_missing_or_invalid')

    if worker_bundle.get('verdict') != 'ACCEPT':
        issues.append('worker_bundle_verdict_not_accept')
    if not sample_proof:
        issues.append('sample_proof_missing_or_unreadable')
    elif sample_proof.get('verdict') != 'ACCEPT':
        issues.append('sample_proof_verdict_not_accept')
    if not gate_bundle:
        issues.append('gate_bundle_missing_or_unreadable')
    elif gate_bundle.get('verdict') != 'ACCEPT':
        issues.append('gate_bundle_verdict_not_accept')
    if not gate_validation:
        issues.append('gate_validation_missing_or_unreadable')
    elif gate_validation.get('verdict') != 'ACCEPT':
        issues.append('gate_validation_verdict_not_accept')

    sample_duplicate_count = sample_proof.get('duplicate_key_count', sample_summary.get('duplicate_key_count'))
    if sample_duplicate_count not in {0, 0.0}:
        issues.append('sample_duplicate_key_count_must_be_zero')

    benchmark_scope = (
        gate_validation.get('benchmark_scope')
        or worker_gate_summary.get('benchmark_scope')
        or gate_profile.get('benchmark_scope')
    )
    if benchmark_scope != 'real_bounded_read_only':
        issues.append('benchmark_scope_not_real_bounded_read_only')

    production_default_allowed = (
        gate_validation.get('production_default_allowed')
        if 'production_default_allowed' in gate_validation
        else worker_gate_summary.get('production_default_allowed', gate_profile.get('production_default_allowed'))
    )
    if production_default_allowed is not False:
        issues.append('production_default_allowed_must_be_false')

    input_row_count = int(
        gate_validation.get('input_row_count')
        or sample_proof.get('row_count')
        or sample_summary.get('row_count')
        or 0
    )
    if input_row_count < int(min_row_count):
        issues.append('input_row_count_below_minimum')
    if resolved_evidence_scope in PRODUCTION_EVIDENCE_SCOPES and int(min_row_count) < 100000:
        issues.append('min_row_count_too_low_for_production_evidence')

    sample_safety = sample_proof.get('safety') or {}
    worker_safety = worker_bundle.get('safety') or {}
    gate_safety = gate_bundle.get('safety') or {}
    _check_safety('sample_safety', sample_safety, issues, require_read_only_input=True)
    _check_safety('safety', worker_safety, issues, require_read_only_input=True)
    for key in ['starts_backfill', 'writes_datamart', 'production_loop_side_effect']:
        if gate_safety.get(key) is not False:
            issues.append(f'gate_safety_{key}_must_be_false')
    if gate_safety and gate_safety.get('uses_real_market_data') is not True:
        issues.append('gate_safety_uses_real_market_data_must_be_true')

    if worker_gate_summary.get('validation_verdict') not in {None, 'ACCEPT'}:
        issues.append('worker_gate_validation_verdict_not_accept')
    if gate_validation_summary and gate_validation_summary.get('verdict') != 'ACCEPT':
        issues.append('gate_validation_summary_verdict_not_accept')

    candidates = _collect_candidates(worker_bundle, gate_bundle)
    if not candidates:
        issues.append('performance_candidates_missing')
    promotion_candidate_count = sum(1 for item in candidates if item.get('performance_verdict') == 'PROMOTE')

    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'issues': issues,
        'worker_bundle_path': str(worker_bundle_path),
        'sample_proof_path': str(sample_proof_path or ''),
        'gate_bundle_path': str(gate_bundle_path or ''),
        'gate_validation_path': str(gate_validation_path or ''),
        'input_row_count': input_row_count,
        'min_row_count': int(min_row_count),
        'evidence_scope': resolved_evidence_scope,
        'benchmark_scope': benchmark_scope,
        'production_default_allowed': production_default_allowed,
        'performance_candidate_count': len(candidates),
        'promotion_candidate_count': promotion_candidate_count,
        'safety': {
            'read_only_input': _flag(worker_safety.get('read_only_input')),
            'starts_backfill': bool(worker_safety.get('starts_backfill')),
            'writes_datamart': bool(worker_safety.get('writes_datamart')),
            'writes_catalog': bool(worker_safety.get('writes_catalog')),
            'production_loop_side_effect': bool(worker_safety.get('production_loop_side_effect')),
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    worker_bundle_path = Path(args.bundle_path)
    worker_bundle = json.loads(worker_bundle_path.read_text())
    payload = validate_payload(
        worker_bundle=worker_bundle,
        worker_bundle_path=worker_bundle_path,
        min_row_count=int(args.min_row_count),
        evidence_scope=args.evidence_scope,
    )
    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if payload['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
