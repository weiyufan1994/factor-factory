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


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def find_branch(plan: dict[str, Any], branch_id: str) -> dict[str, Any]:
    for branch in plan.get('branches') or []:
        if isinstance(branch, dict) and branch.get('branch_id') == branch_id:
            return branch
    raise SystemExit(f'SEARCH_BRANCH_RESULT_INVALID: branch_id not found in plan: {branch_id}')


def load_payload(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    payload_path = Path(path)
    if not payload_path.exists():
        raise SystemExit(f'SEARCH_BRANCH_RESULT_INVALID: payload file not found: {payload_path}')
    return load_json(payload_path)


def update_ledger(ledger_path: Path, branch_id: str, result_path: Path, status: str, outcome: str) -> None:
    if not ledger_path.exists():
        return
    ledger = load_json(ledger_path)
    for branch in ledger.get('branches') or []:
        if isinstance(branch, dict) and branch.get('branch_id') == branch_id:
            branch['status'] = status
            branch['outcome'] = outcome
            branch['last_event'] = 'branch_result_recorded'
            branch['result_path'] = str(result_path)
            branch['updated_at_utc'] = utc_now()
            break
    write_json(ledger_path, ledger)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--branch-id', required=True)
    ap.add_argument('--status', required=True, choices=['completed', 'failed', 'killed', 'blocked', 'inconclusive'])
    ap.add_argument('--outcome', required=True, choices=['improved', 'not_improved', 'bug_found', 'thesis_rejected', 'needs_more_evidence', 'inconclusive'])
    ap.add_argument('--recommendation', required=True, choices=['use_branch_for_next_step3b', 'keep_exploring', 'kill_branch', 'repair_workflow_first', 'needs_human_review'])
    ap.add_argument('--summary', required=True)
    ap.add_argument('--payload-json', default=None, help='Optional JSON file with metrics/evidence/research_assessment overrides.')
    ap.add_argument('--artifact-path', action='append', default=[])
    ap.add_argument('--failure-signature', action='append', default=[])
    args = ap.parse_args()

    rid = args.report_id
    plan_path = OBJ / 'research_iteration_master' / f'program_search_plan__{rid}.json'
    ledger_path = OBJ / 'research_iteration_master' / f'search_branch_ledger__{rid}.json'
    if not plan_path.exists():
        raise SystemExit(f'SEARCH_BRANCH_RESULT_INVALID: missing program search plan {plan_path}')
    plan = load_json(plan_path)
    branch = find_branch(plan, args.branch_id)
    payload = load_payload(args.payload_json)

    research_assessment = {
        'return_source_preserved_or_challenged': payload.get('return_source_preserved_or_challenged') or 'not_assessed',
        'market_structure_lesson': payload.get('market_structure_lesson') or 'not_assessed',
        'knowledge_lesson': payload.get('knowledge_lesson') or 'not_assessed',
        'anti_pattern_observed': payload.get('anti_pattern_observed') or None,
        'overfit_assessment': payload.get('overfit_assessment') or 'not_assessed',
        'falsification_result': payload.get('falsification_result') or 'not_assessed',
    }
    evidence = {
        'metric_delta': payload.get('metric_delta') or {},
        'step4_artifacts': as_list(payload.get('step4_artifacts')) + list(args.artifact_path or []),
        'validator_results': payload.get('validator_results') or {},
        'failure_signatures': as_list(payload.get('failure_signatures')) + list(args.failure_signature or []),
        'notes': as_list(payload.get('notes')),
    }
    result = {
        'report_id': rid,
        'branch_id': args.branch_id,
        'parent_plan_path': str(plan_path),
        'branch_role': branch.get('branch_role'),
        'search_mode': branch.get('search_mode'),
        'status': args.status,
        'outcome': args.outcome,
        'recommendation': args.recommendation,
        'created_at_utc': utc_now(),
        'research_question': branch.get('research_question'),
        'branch_hypothesis': branch.get('hypothesis'),
        'return_source_target': branch.get('return_source_target'),
        'market_structure_hypothesis': branch.get('market_structure_hypothesis'),
        'knowledge_priors': branch.get('knowledge_priors'),
        'researcher_summary': args.summary,
        'research_assessment': research_assessment,
        'evidence': evidence,
        'selection_protocol_snapshot': plan.get('selection_protocol') or {},
        'human_approval_required_before_canonicalization': True,
        'producer': 'program_search_engine_v1',
    }

    out = OBJ / 'research_iteration_master' / f'search_branch_result__{rid}__{args.branch_id}.json'
    write_json(out, result)
    update_ledger(ledger_path, args.branch_id, out, args.status, args.outcome)


if __name__ == '__main__':
    main()
