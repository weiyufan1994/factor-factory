#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
OBJ = FF / 'objects'


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {path}')


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--decision', required=True, choices=['approve', 'reject'])
    ap.add_argument('--notes', default='')
    args = ap.parse_args()

    proposal_path = OBJ / 'research_iteration_master' / f'revision_proposal__{args.report_id}.json'
    if not proposal_path.exists():
        raise SystemExit(f'STEP6_APPROVAL_INVALID: missing proposal {proposal_path}')

    proposal = load_json(proposal_path)
    proposal['proposal_status'] = 'approved_for_application' if args.decision == 'approve' else 'rejected_by_human'
    proposal['approval'] = {
        'status': 'approved' if args.decision == 'approve' else 'rejected',
        'approved_by': 'human',
        'approved_at_utc': utc_now(),
        'approver_notes': args.notes or None,
    }
    write_json(proposal_path, proposal)
