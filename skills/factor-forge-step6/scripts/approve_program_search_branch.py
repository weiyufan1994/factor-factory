#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
OBJ = FF / 'objects'


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {path}')


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def find_branch(plan: dict[str, Any], branch_id: str) -> dict[str, Any]:
    for branch in plan.get('branches') or []:
        if isinstance(branch, dict) and branch.get('branch_id') == branch_id:
            return branch
    raise SystemExit(f'PROGRAM_SEARCH_BRANCH_APPROVAL_INVALID: branch_id not found: {branch_id}')


def update_ledger(ledger_path: Path, branch_id: str, status: str, notes: str) -> None:
    if not ledger_path.exists():
        return
    ledger = load_json(ledger_path)
    for branch in ledger.get('branches') or []:
        if isinstance(branch, dict) and branch.get('branch_id') == branch_id:
            branch['status'] = status
            branch['last_event'] = 'branch_approval_updated'
            branch['approval_notes'] = notes or None
            branch['updated_at_utc'] = utc_now()
            break
    write_json(ledger_path, ledger)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--branch-id', required=True)
    ap.add_argument('--decision', required=True, choices=['approve', 'reject'])
    ap.add_argument('--notes', default='')
    args = ap.parse_args()

    rid = args.report_id
    plan_path = OBJ / 'research_iteration_master' / f'program_search_plan__{rid}.json'
    ledger_path = OBJ / 'research_iteration_master' / f'search_branch_ledger__{rid}.json'
    if not plan_path.exists():
        raise SystemExit(f'PROGRAM_SEARCH_BRANCH_APPROVAL_INVALID: missing plan {plan_path}')

    plan = load_json(plan_path)
    branch = find_branch(plan, args.branch_id)
    status = 'approved' if args.decision == 'approve' else 'rejected'
    branch['status'] = status
    branch['approval'] = {
        'status': status,
        'approved_by': 'human',
        'approved_at_utc': utc_now(),
        'approver_notes': args.notes or None,
    }
    plan['status'] = 'partially_approved' if args.decision == 'approve' else plan.get('status', 'pending_human_approval')
    plan.setdefault('approval_history', []).append({
        'branch_id': args.branch_id,
        'decision': args.decision,
        'notes': args.notes or None,
        'created_at_utc': utc_now(),
    })
    write_json(plan_path, plan)
    update_ledger(ledger_path, args.branch_id, status, args.notes)


if __name__ == '__main__':
    main()
