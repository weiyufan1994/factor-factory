#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
OBJ = FF / 'objects'
REQUIRED_HARD_GUARDS = {
    'no_portfolio_expression_repair',
    'no_short_leg_adoption',
    'no_decile_trading',
    'no_shared_clean_data_mutation',
}
FORBIDDEN_TERMS = [
    'portfolio expression',
    'portfolio',
    'rebalance',
    'short leg',
    'short-leg',
    'short_side',
    'short side',
    'long-short',
    'long short',
    'decile trading',
    'buy decile',
    'sell decile',
    'shared clean data',
    'clean data mutation',
    'mutate clean data',
]
SKIP_SCAN_KEYS = {'hard_guards', 'forbidden_search', 'search_policy_decision_source'}


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


def forbidden_hits(value: Any, path: str = 'branch') -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in SKIP_SCAN_KEYS:
                continue
            hits.extend(forbidden_hits(child, f'{path}.{key}'))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            hits.extend(forbidden_hits(child, f'{path}[{idx}]'))
    elif isinstance(value, str):
        lowered = value.lower()
        for term in FORBIDDEN_TERMS:
            if term in lowered:
                hits.append({'path': path, 'pattern': term})
    return hits


def assert_plan_valid(report_id: str) -> None:
    cmd = [
        sys.executable,
        str(REPO_ROOT / 'skills/factor-forge-step6/scripts/validate_program_search_plan.py'),
        '--report-id',
        report_id,
    ]
    env = os.environ.copy()
    env['FACTORFORGE_ROOT'] = str(FF)
    proc = subprocess.run(cmd, cwd=REPO_ROOT, env=env, text=True, capture_output=True)
    if proc.returncode != 0:
        tail = (proc.stdout + '\n' + proc.stderr)[-2000:]
        raise SystemExit(f'PROGRAM_SEARCH_BRANCH_APPROVAL_INVALID: source plan validator BLOCK\n{tail}')


def assert_branch_approvable(plan: dict[str, Any], branch: dict[str, Any], approval_path: Path, notes: str) -> None:
    if plan.get('status') != 'pending_human_approval':
        raise SystemExit(f'PROGRAM_SEARCH_BRANCH_APPROVAL_INVALID: plan status {plan.get("status")} cannot be approved')
    if branch.get('status') != 'proposed':
        raise SystemExit(f'PROGRAM_SEARCH_BRANCH_APPROVAL_INVALID: branch status {branch.get("status")} is not proposed')
    if branch.get('requires_human_approval_before_execution') is not True:
        raise SystemExit('PROGRAM_SEARCH_BRANCH_APPROVAL_INVALID: branch must require human approval')
    if branch.get('execution_allowed_by_default') is not False:
        raise SystemExit('PROGRAM_SEARCH_BRANCH_APPROVAL_INVALID: execution_allowed_by_default must be false')
    if not notes.strip():
        raise SystemExit('PROGRAM_SEARCH_BRANCH_APPROVAL_INVALID: approval notes are required')
    if approval_path.exists():
        raise SystemExit(f'PROGRAM_SEARCH_BRANCH_APPROVAL_INVALID: approval already exists {approval_path}')
    hard_guards = set(branch.get('hard_guards') or [])
    if not REQUIRED_HARD_GUARDS.issubset(hard_guards):
        raise SystemExit(f'PROGRAM_SEARCH_BRANCH_APPROVAL_INVALID: missing hard guards {sorted(REQUIRED_HARD_GUARDS - hard_guards)}')
    hits = forbidden_hits(branch)
    if hits:
        raise SystemExit(f'PROGRAM_SEARCH_BRANCH_APPROVAL_INVALID: forbidden branch text {hits}')


def update_ledger(ledger_path: Path, branch_id: str, status: str, notes: str, approval_path: Path) -> None:
    if not ledger_path.exists():
        return
    ledger = load_json(ledger_path)
    for branch in ledger.get('branches') or []:
        if isinstance(branch, dict) and branch.get('branch_id') == branch_id:
            branch['status'] = status
            branch['last_event'] = 'branch_approval_updated'
            branch['approval_notes'] = notes or None
            branch['approval_path'] = str(approval_path)
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
    approval_path = OBJ / 'research_iteration_master' / f'search_branch_approval__{rid}__{args.branch_id}.json'
    assert_plan_valid(rid)
    assert_branch_approvable(plan, branch, approval_path, args.notes)
    status = 'approved' if args.decision == 'approve' else 'rejected'
    approval = {
        'report_id': rid,
        'branch_id': args.branch_id,
        'approval_status': status,
        'approved_by': 'human',
        'approval_time': utc_now(),
        'approval_notes': args.notes,
        'source_plan_identity': {
            'plan_path': str(plan_path),
            'plan_status': plan.get('status'),
            'producer': plan.get('producer'),
            'created_at_utc': plan.get('created_at_utc'),
        },
        'source_branch_snapshot': branch,
        'hard_guards_confirmed': True,
        'execution_allowed_by_default': False,
        'canonical_write_permission': False,
    }
    write_json(approval_path, approval)
    update_ledger(ledger_path, args.branch_id, status, args.notes, approval_path)


if __name__ == '__main__':
    main()
