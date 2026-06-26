#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.operator_backend_registry import resolve_operator_backend  # noqa: E402


def _load_readiness_module() -> Any:
    path = Path(__file__).resolve().parent / 'validate_operator_backend_readiness.py'
    spec = importlib.util.spec_from_file_location('validate_operator_backend_readiness', path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load readiness validator: {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Audit operator backend replacement evidence and runtime registry decision without mutating config.'
    )
    parser.add_argument('--operator-id', required=True)
    parser.add_argument('--default-backend', required=True)
    parser.add_argument('--configured-backend', required=True)
    parser.add_argument('--safe-validation-path', required=True)
    parser.add_argument('--approval-validation-path', required=True)
    parser.add_argument('--replacement-plan-path', required=True)
    parser.add_argument('--output-path', required=True)
    return parser.parse_args(argv)


def _load_json(path: str | Path) -> dict[str, Any] | None:
    candidate = Path(path)
    if not candidate.exists():
        return None
    return json.loads(candidate.read_text(encoding='utf-8'))


def audit_payload(
    *,
    operator_id: str,
    default_backend: str,
    configured_backend: str,
    safe_validation_path: Path,
    approval_validation_path: Path,
    replacement_plan_path: Path,
) -> dict[str, Any]:
    readiness_module = _load_readiness_module()
    readiness = readiness_module.validate_payload(
        operator_id=operator_id,
        safe_validation=_load_json(safe_validation_path),
        approval_validation=_load_json(approval_validation_path),
        replacement_plan=_load_json(replacement_plan_path),
        safe_validation_path=safe_validation_path,
        approval_validation_path=approval_validation_path,
        replacement_plan_path=replacement_plan_path,
    )
    approval_validation = _load_json(approval_validation_path)
    runtime_decision = resolve_operator_backend(
        operator_id=operator_id,
        default_backend=default_backend,
        configured_backend=configured_backend,
        approval_validation=approval_validation,
    )
    issues: list[str] = []
    if readiness.get('verdict') != 'ACCEPT':
        issues.append('readiness_not_accept')
    if runtime_decision.get('replacement_allowed') is not True:
        issues.append('runtime_registry_replacement_not_allowed')
    if runtime_decision.get('selected_backend') != readiness.get('selected_backend'):
        issues.append('runtime_selected_backend_mismatch_readiness')
    if runtime_decision.get('selected_backend') != configured_backend:
        issues.append('runtime_selected_backend_mismatch_configured_backend')
    return {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'issues': issues,
        'operator_id': operator_id,
        'default_backend': default_backend,
        'configured_backend': configured_backend,
        'readiness': readiness,
        'runtime_decision': runtime_decision,
        'required_next_step': 'manual_config_change_after_review' if not issues else 'do_not_change_backend_config',
        'safety': {
            'writes_backend_config': False,
            'writes_datamart': False,
            'production_loop_side_effect': False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = audit_payload(
        operator_id=str(args.operator_id),
        default_backend=str(args.default_backend),
        configured_backend=str(args.configured_backend),
        safe_validation_path=Path(args.safe_validation_path).expanduser(),
        approval_validation_path=Path(args.approval_validation_path).expanduser(),
        replacement_plan_path=Path(args.replacement_plan_path).expanduser(),
    )
    output_path = Path(args.output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if payload['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
