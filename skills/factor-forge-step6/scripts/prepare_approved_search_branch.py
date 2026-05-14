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


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding='utf-8')
    print(f'[WRITE] {path}')


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def find_branch(plan: dict[str, Any], branch_id: str) -> dict[str, Any]:
    for branch in plan.get('branches') or []:
        if isinstance(branch, dict) and branch.get('branch_id') == branch_id:
            return branch
    raise SystemExit(f'PROGRAM_SEARCH_BRANCH_PREP_INVALID: branch_id not found: {branch_id}')


def bullet(values: list[Any]) -> str:
    rows = []
    for value in values:
        rows.append(f'- {value}')
    return '\n'.join(rows) if rows else '- none'


def build_markdown(report_id: str, branch: dict[str, Any], taskbook: dict[str, Any]) -> str:
    return f"""# Program Search Branch Taskbook

report_id: `{report_id}`
branch_id: `{branch.get('branch_id')}`
branch_role: `{branch.get('branch_role')}`
search_mode: `{branch.get('search_mode')}`

## Research Question

{branch.get('research_question')}

## Hypothesis

{branch.get('hypothesis')}

## Return Source Target

`{branch.get('return_source_target')}`

## Market Structure Hypothesis

```json
{json.dumps(branch.get('market_structure_hypothesis') or {{}}, ensure_ascii=False, indent=2)}
```

## Knowledge Priors

```json
{json.dumps(branch.get('knowledge_priors') or {{}}, ensure_ascii=False, indent=2)}
```

## Allowed Write Scope

{bullet(taskbook['allowed_write_scope'])}

## Must Not Do

{bullet(taskbook['must_not_do'])}

## Required Evidence

{bullet(taskbook['required_evidence'])}

## Success Criteria

{bullet(branch.get('success_criteria') or [])}

## Falsification Tests

{bullet(branch.get('falsification_tests') or [])}

## Completion Command

After the branch is finished, record the result with:

```bash
python3 skills/factor-forge-step6/scripts/record_search_branch_result.py \\
  --report-id {report_id!r} \\
  --branch-id {branch.get('branch_id')!r} \\
  --status completed \\
  --outcome improved \\
  --recommendation needs_human_review \\
  --summary '<research summary>' \\
  --payload-json <branch_result_payload.json>

python3 skills/factor-forge-step6/scripts/validate_search_branch_result.py \\
  --report-id {report_id!r} \\
  --branch-id {branch.get('branch_id')!r}
```

Do not update canonical Step3B or `handoff_to_step3b` directly. Step6 merge and human approval are required.
"""


def update_ledger(ledger_path: Path, branch_id: str, taskbook_path: Path) -> None:
    if not ledger_path.exists():
        return
    ledger = load_json(ledger_path)
    for branch in ledger.get('branches') or []:
        if isinstance(branch, dict) and branch.get('branch_id') == branch_id:
            branch['status'] = 'prepared'
            branch['last_event'] = 'approved_branch_taskbook_prepared'
            branch['taskbook_path'] = str(taskbook_path)
            branch['branch_manifest_path'] = str(taskbook_path.parent / 'branch_manifest.json')
            branch['updated_at_utc'] = utc_now()
            break
    write_json(ledger_path, ledger)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--branch-id', required=True)
    args = ap.parse_args()

    rid = args.report_id
    plan_path = OBJ / 'research_iteration_master' / f'program_search_plan__{rid}.json'
    ledger_path = OBJ / 'research_iteration_master' / f'search_branch_ledger__{rid}.json'
    if not plan_path.exists():
        raise SystemExit(f'PROGRAM_SEARCH_BRANCH_PREP_INVALID: missing plan {plan_path}')

    plan = load_json(plan_path)
    branch = find_branch(plan, args.branch_id)
    approval_path = OBJ / 'research_iteration_master' / f'search_branch_approval__{rid}__{args.branch_id}.json'
    if not approval_path.exists():
        raise SystemExit(f'PROGRAM_SEARCH_BRANCH_APPROVAL_REQUIRED: missing approval {approval_path}')
    approval = load_json(approval_path)
    if approval.get('approval_status') != 'approved':
        raise SystemExit(f'PROGRAM_SEARCH_BRANCH_APPROVAL_REQUIRED: approval_status={approval.get("approval_status")}')
    if approval.get('canonical_write_permission') is not False:
        raise SystemExit('PROGRAM_SEARCH_BRANCH_PREP_INVALID: approval cannot grant canonical write permission')

    branch_root = FF / 'research_branches' / rid / args.branch_id
    manifest_path = branch_root / 'branch_manifest.json'
    if manifest_path.exists():
        raise SystemExit(f'PROGRAM_SEARCH_BRANCH_PREP_INVALID: branch already prepared {manifest_path}')
    allowed_write_scope = [
        str(branch_root),
        str(OBJ / 'research_iteration_master' / f'search_branch_result__{rid}__{args.branch_id}.json'),
        str(OBJ / 'research_iteration_master' / f'search_branch_ledger__{rid}.json'),
    ]
    branch_root.mkdir(parents=True, exist_ok=True)

    taskbook = {
        'report_id': rid,
        'branch_id': args.branch_id,
        'created_at_utc': utc_now(),
        'branch_status': 'prepared',
        'source_plan_path': str(plan_path),
        'source_approval_path': str(approval_path),
        'branch': branch,
        'allowed_write_scope': allowed_write_scope,
        'canonical_write_permission': False,
        'execution_allowed': False,
        'requires_worker_specific_command': True,
        'must_not_do': [
            'do not mutate shared clean data',
            'do not overwrite canonical Step3B implementation',
            'do not update handoff_to_step3b or handoff_to_step4 directly',
            'do not claim success without Step4 evidence or explicit failure signature',
            'do not hide failed trials',
        ],
        'required_evidence': [
            'research summary tied to return source and market structure',
            'falsification result',
            'overfit assessment',
            'metric_delta or failure signature',
            'artifact paths or validator outputs',
            'recommendation for Step6 merge',
        ],
        'branch_root': str(branch_root),
        'producer': 'program_search_engine_v1',
    }
    manifest = {
        'report_id': rid,
        'branch_id': args.branch_id,
        'branch_status': 'prepared',
        'source_plan_path': str(plan_path),
        'source_approval_path': str(approval_path),
        'isolated_workspace': str(branch_root),
        'allowed_write_scope': allowed_write_scope,
        'forbidden_write_scope': [
            'objects/handoff',
            f'generated_code/{rid}',
            'data/clean',
            'objects/factor_library_official',
            'objects/implementation_plan_master',
        ],
        'canonical_write_permission': False,
        'execution_allowed': False,
        'requires_worker_specific_command': True,
    }
    input_snapshot = {
        'report_id': rid,
        'branch_id': args.branch_id,
        'source_plan_path': str(plan_path),
        'source_approval_path': str(approval_path),
        'branch_snapshot': branch,
        'search_policy_decision': plan.get('search_policy_decision') or {},
    }

    taskbook_path = branch_root / 'branch_taskbook.json'
    taskbook_md_path = branch_root / 'README.md'
    write_json(taskbook_path, taskbook)
    write_json(manifest_path, manifest)
    write_json(branch_root / 'input_snapshot.json', input_snapshot)
    write_text(taskbook_md_path, build_markdown(rid, branch, taskbook))
    update_ledger(ledger_path, args.branch_id, taskbook_path)


if __name__ == '__main__':
    main()
