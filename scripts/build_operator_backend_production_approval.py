#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ALLOWED_EVIDENCE_SCOPES = {'production_scale', 'full_is'}
FALSE_SAFETY_FLAGS = ['starts_backfill', 'writes_datamart', 'writes_catalog', 'production_loop_side_effect']


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Build a read-only production approval artifact for an operator backend candidate.'
    )
    parser.add_argument('--profile-path', required=True)
    parser.add_argument('--validation-path', required=True)
    parser.add_argument('--safe-worker-bundle-path', required=True)
    parser.add_argument('--safe-worker-validation-path', required=True)
    parser.add_argument('--operator-id', required=True)
    parser.add_argument('--approved-backend', required=True)
    parser.add_argument('--evidence-scope', required=True, choices=sorted(ALLOWED_EVIDENCE_SCOPES | {'bounded_worker'}))
    parser.add_argument('--approved-by', required=True)
    parser.add_argument('--approval-reason', required=True)
    parser.add_argument('--min-input-row-count', type=int, default=100000)
    parser.add_argument('--output-path', required=True)
    return parser.parse_args(argv)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_for(profile: dict[str, Any], *, operator_id: str, approved_backend: str) -> dict[str, Any] | None:
    gate = profile.get('performance_gate') or {}
    for candidate in gate.get('candidates') or []:
        if candidate.get('operator_id') == operator_id and candidate.get('candidate_backend') == approved_backend:
            return candidate
    return None


def _safety_issues(safety: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for key in FALSE_SAFETY_FLAGS:
        if safety.get(key) is not False:
            issues.append(f'safety_{key}_must_be_false')
    return issues


def build_approval(
    *,
    profile: dict[str, Any],
    validation: dict[str, Any],
    safe_worker_bundle: dict[str, Any],
    safe_worker_validation: dict[str, Any],
    paths: dict[str, Path],
    operator_id: str,
    approved_backend: str,
    evidence_scope: str,
    approved_by: str,
    approval_reason: str,
    min_input_row_count: int,
) -> dict[str, Any]:
    issues: list[str] = []
    if evidence_scope not in ALLOWED_EVIDENCE_SCOPES:
        issues.append('evidence_scope_not_production_scale_or_full_is')
    validation_evidence_scope = str(safe_worker_validation.get('evidence_scope') or '')
    if validation_evidence_scope != evidence_scope:
        issues.append('safe_worker_validation_evidence_scope_mismatch')
    bundle_evidence_scope = str(safe_worker_bundle.get('evidence_scope') or '')
    if bundle_evidence_scope and bundle_evidence_scope != validation_evidence_scope:
        issues.append('safe_worker_bundle_evidence_scope_mismatch')
    if profile.get('verdict') != 'ACCEPT':
        issues.append('profile_verdict_not_accept')
    if not approved_by or str(approved_by).startswith('<'):
        issues.append('approved_by_missing_or_placeholder')
    if not approval_reason or str(approval_reason).startswith('<'):
        issues.append('approval_reason_missing_or_placeholder')
    if validation.get('verdict') != 'ACCEPT':
        issues.append('validation_verdict_not_accept')
    if safe_worker_bundle.get('verdict') != 'ACCEPT':
        issues.append('safe_worker_bundle_verdict_not_accept')
    if safe_worker_validation.get('verdict') != 'ACCEPT':
        issues.append('safe_worker_validation_verdict_not_accept')
    if safe_worker_validation.get('operator_replacement_verdict') != 'PROMOTE':
        issues.append('safe_worker_validation_operator_replacement_not_promote')
    if safe_worker_validation.get('production_default_allowed') is not False:
        issues.append('safe_worker_validation_production_default_allowed_must_be_false')
    input_row_count = int(safe_worker_validation.get('input_row_count') or 0)
    if input_row_count < int(min_input_row_count):
        issues.append('safe_worker_validation_input_row_count_below_minimum')
    candidate = _candidate_for(profile, operator_id=operator_id, approved_backend=approved_backend)
    if not candidate:
        issues.append('promoted_candidate_missing_for_operator_backend')
    elif candidate.get('performance_verdict') != 'PROMOTE':
        issues.append('candidate_performance_verdict_not_promote')
    issues.extend(_safety_issues(safe_worker_bundle.get('safety') or {}))
    issues.extend(f'safe_worker_validation_{item}' for item in _safety_issues(safe_worker_validation.get('safety') or {}))

    proof_paths = {name: str(path) for name, path in paths.items()}
    proof_hashes = {name: _sha256(path) for name, path in paths.items()}
    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'approval_scope': 'production_default_backend',
        'operator_id': operator_id,
        'approved_backend': approved_backend,
        'production_default_allowed': not issues,
        'approved_by': approved_by,
        'approval_reason': approval_reason,
        'evidence_scope': evidence_scope,
        'issues': issues,
        'evidence': {
            'profile_path': proof_paths['profile_path'],
            'validation_path': proof_paths['validation_path'],
            'safe_worker_bundle_path': proof_paths['safe_worker_bundle_path'],
            'safe_worker_validation_path': proof_paths['safe_worker_validation_path'],
            'sha256': proof_hashes,
            'input_row_count': input_row_count,
            'min_input_row_count': int(min_input_row_count),
            'benchmark_scope': safe_worker_validation.get('benchmark_scope'),
            'evidence_scope': validation_evidence_scope,
            'date_count': safe_worker_validation.get('date_count'),
            'min_trade_date': safe_worker_validation.get('min_trade_date'),
            'max_trade_date': safe_worker_validation.get('max_trade_date'),
            'candidate': candidate or {},
        },
        'generated_at_utc': utc_now(),
        'safety': {
            'writes_backend_config': False,
            'writes_datamart': False,
            'writes_catalog': False,
            'production_loop_side_effect': False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = {
        'profile_path': Path(args.profile_path),
        'validation_path': Path(args.validation_path),
        'safe_worker_bundle_path': Path(args.safe_worker_bundle_path),
        'safe_worker_validation_path': Path(args.safe_worker_validation_path),
    }
    payload = build_approval(
        profile=_load_json(paths['profile_path']),
        validation=_load_json(paths['validation_path']),
        safe_worker_bundle=_load_json(paths['safe_worker_bundle_path']),
        safe_worker_validation=_load_json(paths['safe_worker_validation_path']),
        paths=paths,
        operator_id=str(args.operator_id),
        approved_backend=str(args.approved_backend),
        evidence_scope=str(args.evidence_scope),
        approved_by=str(args.approved_by),
        approval_reason=str(args.approval_reason),
        min_input_row_count=int(args.min_input_row_count),
    )
    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'verdict': payload['verdict'], 'output_path': str(output_path), 'issues': payload['issues']}, ensure_ascii=False, indent=2))
    return 0 if payload['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
