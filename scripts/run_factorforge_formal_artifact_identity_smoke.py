#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.artifact_identity import validate_top_level_formal_artifact_identity


def valid_payload() -> dict:
    return {
        'report_id': 'R',
        'factor_id': 'F',
        'run_id': 'RUN',
        'artifact_root': '/tmp/factorforge',
        'producer': 'step4',
        'status': 'success',
        'verdict': 'PASS',
        'artifact_identity': {'report_id': 'R', 'factor_id': 'F', 'run_id': 'RUN'},
    }


def has(issues: list[dict], code: str) -> bool:
    return any(item.get('code') == code for item in issues)


def main() -> None:
    cases: dict[str, dict] = {}
    payload = valid_payload()
    payload.pop('run_id')
    issues = validate_top_level_formal_artifact_identity(payload, label='smoke')
    cases['missing_top_level_identity_blocks'] = {'ok': has(issues, 'BLOCK_FORMAL_ARTIFACT_TOP_LEVEL_IDENTITY_MISSING'), 'issues': issues}

    payload = valid_payload()
    payload['run_id'] = 'OTHER'
    issues = validate_top_level_formal_artifact_identity(payload, label='smoke')
    cases['top_level_identity_mismatch_blocks'] = {'ok': has(issues, 'BLOCK_FORMAL_ARTIFACT_TOP_LEVEL_IDENTITY_MISMATCH'), 'issues': issues}

    issues = validate_top_level_formal_artifact_identity(valid_payload(), label='smoke')
    cases['valid_top_level_identity_passes'] = {'ok': not issues, 'issues': issues}

    failed = [name for name, item in cases.items() if not item.get('ok')]
    summary = {'verdict': 'ACCEPT' if not failed else 'BLOCK', 'cases': cases, 'failed': failed}
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
