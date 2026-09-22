#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
OBJ = FF / 'objects'


def run_checked(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return {
        'cmd': cmd,
        'returncode': proc.returncode,
        'stdout': proc.stdout,
        'stderr': proc.stderr,
    }


def resolve_python() -> str:
    candidates = [
        os.getenv('FACTORFORGE_PYTHON'),
        str(LEGACY_WORKSPACE / '.venvs' / 'quant-research' / 'bin' / 'python'),
        sys.executable,
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return sys.executable


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def write_summary(report_id: str, payload: dict) -> Path:
    out = OBJ / 'research_iteration_master' / f'step6_autoloop_summary__{report_id}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return out


def approved_proposal_path(report_id: str) -> Path | None:
    proposal_path = OBJ / 'research_iteration_master' / f'revision_proposal__{report_id}.json'
    if not proposal_path.exists():
        return None
    proposal = load_json(proposal_path)
    approval_status = (((proposal.get('approval') or {}).get('status')) or '').lower()
    if approval_status == 'approved':
        return proposal_path
    return None


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--max-iterations', type=int, default=2)
    ap.add_argument('--continue-approved', action='store_true')
    args = ap.parse_args()

    py = resolve_python()
    rid = args.report_id
    summary = {
        'report_id': rid,
        'runtime_root': str(FF),
        'max_iterations': args.max_iterations,
        'rounds': [],
        'result': 'PASS',
        'final_decision': None,
    }

    approved_path = approved_proposal_path(rid) if args.continue_approved else None
    consumed_existing_approval = approved_path is not None
    if approved_path is not None:
        approval_round = {
            'round': 0,
            'decision': 'apply_approved_iteration',
            'proposal_path': str(approved_path),
            'steps': [{
                'step': 'reuse_approved_revision_proposal',
                'returncode': 0,
                'stdout': f'Using existing approved proposal: {approved_path}\n',
                'stderr': '',
                'cmd': None,
            }],
        }
        apply_cmd = [
            py,
            str(REPO_ROOT / 'scripts' / 'run_factorforge_ultimate.py'),
            '--report-id',
            rid,
            '--apply-approved-revision',
            '--start-step',
            '4',
            '--end-step',
            '6',
        ]
        apply_result = run_checked(apply_cmd)
        apply_result['step'] = 'apply_approved_revision_via_ultimate'
        approval_round['steps'].append(apply_result)
        summary['rounds'].append(approval_round)
        if apply_result['returncode'] != 0:
            summary['result'] = 'FAIL'
            out = write_summary(rid, summary)
            print(json.dumps({'result': summary['result'], 'summary_path': str(out)}, ensure_ascii=False, indent=2))
            raise SystemExit(1)

    for loop_idx in range(1, args.max_iterations + 1):
        round_payload = {'round': loop_idx, 'steps': []}

        for name, cmd in [
            ('run_factorforge_ultimate_step4_6', [
                py,
                str(REPO_ROOT / 'scripts' / 'run_factorforge_ultimate.py'),
                '--report-id',
                rid,
                '--start-step',
                '4',
                '--end-step',
                '6',
            ]),
        ]:
            result = run_checked(cmd)
            result['step'] = name
            round_payload['steps'].append(result)
            if result['returncode'] != 0:
                summary['result'] = 'FAIL'
                summary['rounds'].append(round_payload)
                out = write_summary(rid, summary)
                print(json.dumps({'result': summary['result'], 'summary_path': str(out)}, ensure_ascii=False, indent=2))
                raise SystemExit(1)

        iteration_path = OBJ / 'research_iteration_master' / f'research_iteration_master__{rid}.json'
        if not iteration_path.exists():
            summary['result'] = 'FAIL'
            round_payload['error'] = 'research_iteration_master missing after run_step6_controller'
            summary['rounds'].append(round_payload)
            out = write_summary(rid, summary)
            print(json.dumps({'result': summary['result'], 'summary_path': str(out)}, ensure_ascii=False, indent=2))
            raise SystemExit(1)

        iteration = load_json(iteration_path)
        decision = (((iteration.get('research_judgment') or {}).get('decision')) or 'needs_human_review')
        round_payload['decision'] = decision
        round_payload['modification_targets'] = ((iteration.get('loop_action') or {}).get('modification_targets')) or []
        summary['rounds'].append(round_payload)
        summary['final_decision'] = decision

        if decision != 'iterate':
            break

        proposal_path = OBJ / 'research_iteration_master' / f'revision_proposal__{rid}.json'
        should_build_proposal = True
        if args.continue_approved and approved_path is not None:
            should_build_proposal = True

        if should_build_proposal:
            proposal_cmd = [py, str(REPO_ROOT / 'skills' / 'factor-forge-step6' / 'scripts' / 'build_step6_revision_proposal.py'), '--report-id', rid]
            proposal_result = run_checked(proposal_cmd)
            proposal_result['step'] = 'build_step6_revision_proposal'
            round_payload['steps'].append(proposal_result)
            if proposal_result['returncode'] != 0:
                summary['result'] = 'FAIL'
                out = write_summary(rid, summary)
                print(json.dumps({'result': summary['result'], 'summary_path': str(out)}, ensure_ascii=False, indent=2))
                raise SystemExit(1)
        round_payload['proposal_path'] = str(proposal_path)

        if (not args.continue_approved) or consumed_existing_approval:
            summary['result'] = 'AWAITING_APPROVAL'
            summary['final_decision'] = 'awaiting_human_approval'
            out = write_summary(rid, summary)
            print(json.dumps({'result': summary['result'], 'summary_path': str(out), 'proposal_path': str(proposal_path)}, ensure_ascii=False, indent=2))
            raise SystemExit(0)

        apply_cmd = [
            py,
            str(REPO_ROOT / 'scripts' / 'run_factorforge_ultimate.py'),
            '--report-id',
            rid,
            '--apply-approved-revision',
            '--start-step',
            '4',
            '--end-step',
            '6',
        ]
        apply_result = run_checked(apply_cmd)
        apply_result['step'] = 'apply_approved_revision_via_ultimate'
        round_payload['steps'].append(apply_result)
        if apply_result['returncode'] != 0:
            summary['result'] = 'FAIL'
            out = write_summary(rid, summary)
            print(json.dumps({'result': summary['result'], 'summary_path': str(out)}, ensure_ascii=False, indent=2))
            raise SystemExit(1)

    out = write_summary(rid, summary)
    print(json.dumps({'result': summary['result'], 'summary_path': str(out), 'final_decision': summary['final_decision']}, ensure_ascii=False, indent=2))
