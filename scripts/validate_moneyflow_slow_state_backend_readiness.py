#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


def _load_generic_validator() -> Any:
    path = Path(__file__).resolve().parent / 'validate_operator_backend_readiness.py'
    spec = importlib.util.spec_from_file_location('validate_operator_backend_readiness', path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load generic readiness validator: {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Validate whether moneyflow_slow_state_v1 has a complete reviewed chain for manual backend replacement.'
    )
    parser.add_argument('--safe-worker-validation-path', required=True)
    parser.add_argument('--approval-validation-path', required=True)
    parser.add_argument('--replacement-plan-path', required=True)
    parser.add_argument('--output-path', required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    generic = _load_generic_validator()
    exit_code = generic.main([
        '--operator-id',
        'moneyflow_slow_state_v1',
        '--safe-validation-path',
        str(args.safe_worker_validation_path),
        '--approval-validation-path',
        str(args.approval_validation_path),
        '--replacement-plan-path',
        str(args.replacement_plan_path),
        '--output-path',
        str(args.output_path),
    ])
    output_path = Path(args.output_path)
    if output_path.exists():
        payload = json.loads(output_path.read_text(encoding='utf-8'))
        issues = list(payload.get('issues') or [])
        compat_issues = [
            item.replace('safe_validation_', 'safe_worker_validation_', 1)
            for item in issues
            if str(item).startswith('safe_validation_')
        ]
        for item in compat_issues:
            if item not in issues:
                issues.append(item)
        payload['issues'] = issues
        payload['compat_wrapper'] = 'validate_moneyflow_slow_state_backend_readiness.py'
        payload['safe_worker_validation_path'] = str(args.safe_worker_validation_path)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
