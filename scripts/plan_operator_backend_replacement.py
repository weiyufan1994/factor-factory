#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Create a read-only plan artifact for an approved operator backend replacement.')
    parser.add_argument('--approval-validation-path', required=True)
    parser.add_argument('--target-scope', required=True)
    parser.add_argument('--output-path', required=True)
    return parser.parse_args(argv)


def build_plan(*, approval_validation: dict[str, Any], approval_validation_path: Path, target_scope: str) -> dict[str, Any]:
    decision = approval_validation.get('decision') or {}
    approval_ok = approval_validation.get('verdict') == 'ACCEPT' and decision.get('replacement_allowed') is True
    default_backend = str(decision.get('default_backend') or approval_validation.get('default_backend') or '')
    selected_backend = str(decision.get('selected_backend') or default_backend)
    proof_paths = {
        'profile_path': str(approval_validation.get('profile_path') or ''),
        'validation_path': str(approval_validation.get('validation_path') or ''),
        'approval_path': str(approval_validation.get('approval_path') or ''),
        'safe_worker_bundle_path': str(approval_validation.get('safe_worker_bundle_path') or ''),
        'safe_worker_validation_path': str(approval_validation.get('safe_worker_validation_path') or ''),
    }
    evidence_scope = str(
        approval_validation.get('approval_evidence_scope')
        or approval_validation.get('safe_worker_validation_evidence_scope')
        or ''
    )
    issues: list[str] = []
    if not approval_ok:
        issues.append('approval_validation_not_accept')
    if not default_backend:
        issues.append('default_backend_missing')
    if not selected_backend:
        issues.append('selected_backend_missing')
    if approval_ok and selected_backend == default_backend:
        issues.append('selected_backend_equals_default_backend')
    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'target_scope': target_scope,
        'replacement_action': 'plan_only',
        'approval_validation_path': str(approval_validation_path),
        'operator_id': str(decision.get('operator_id') or approval_validation.get('operator_id') or ''),
        'default_backend': default_backend,
        'selected_backend': selected_backend if approval_ok else default_backend,
        'candidate_backend': str(decision.get('candidate_backend') or approval_validation.get('approved_backend') or ''),
        'evidence_scope': evidence_scope,
        'proof_paths': proof_paths,
        'issues': issues,
        'decision': decision,
        'required_next_step': 'manual_config_change_after_review' if not issues else 'do_not_change_backend_config',
        'safety': {
            'writes_backend_config': False,
            'writes_datamart': False,
            'production_loop_side_effect': False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    approval_validation_path = Path(args.approval_validation_path)
    payload = build_plan(
        approval_validation=json.loads(approval_validation_path.read_text()),
        approval_validation_path=approval_validation_path,
        target_scope=str(args.target_scope),
    )
    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if payload['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
