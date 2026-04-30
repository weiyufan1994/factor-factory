#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.runtime_context import resolve_factorforge_context, utc_now, write_json_atomic


STEP_ORDER = ['2', '3', '3b', '4', '5', '6']
START_ALIASES = {
    '2': '2',
    'step2': '2',
    '3': '3',
    '3a': '3',
    'step3': '3',
    'step3a': '3',
    '3b': '3b',
    'step3b': '3b',
    '4': '4',
    'step4': '4',
    '5': '5',
    'step5': '5',
    '6': '6',
    'step6': '6',
}
END_ALIASES = START_ALIASES | {'all': '6'}


@dataclass
class CommandResult:
    name: str
    command: list[str]
    cwd: str
    started_at_utc: str
    finished_at_utc: str | None = None
    returncode: int | None = None
    stdout_tail: str = ''
    stderr_tail: str = ''
    status: str = 'NOT_RUN'


def normalize_step(raw: str, aliases: dict[str, str]) -> str:
    key = raw.strip().lower().replace('_', '').replace('-', '')
    if key not in aliases:
        raise SystemExit(f'unsupported step: {raw!r}')
    return aliases[key]


def step_slice(start: str, end: str) -> list[str]:
    s = STEP_ORDER.index(start)
    e = STEP_ORDER.index(end)
    if e < s:
        raise SystemExit(f'end-step {end} is before start-step {start}')
    return STEP_ORDER[s:e + 1]


def tail(text: str, limit: int = 12000) -> str:
    return text[-limit:] if len(text) > limit else text


def run_command(name: str, command: list[str], *, cwd: Path, env: dict[str, str], dry_run: bool = False) -> CommandResult:
    item = CommandResult(name=name, command=command, cwd=str(cwd), started_at_utc=utc_now())
    if dry_run:
        item.status = 'DRY_RUN'
        item.returncode = 0
        item.finished_at_utc = utc_now()
        return item
    proc = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True)
    item.returncode = proc.returncode
    item.stdout_tail = tail(proc.stdout)
    item.stderr_tail = tail(proc.stderr)
    item.finished_at_utc = utc_now()
    item.status = 'PASS' if proc.returncode == 0 else 'FAIL'
    return item


def object_status(path: Path) -> dict[str, Any]:
    return {
        'path': str(path),
        'exists': path.exists(),
        'size': path.stat().st_size if path.exists() else None,
        'mtime': path.stat().st_mtime if path.exists() else None,
    }


def collect_expected_artifacts(manifest: dict[str, Any]) -> dict[str, Any]:
    paths: dict[str, str] = {}
    for section in ['objects', 'runs', 'evaluations']:
        for key, value in (manifest.get(section) or {}).items():
            if isinstance(value, str):
                paths[f'{section}.{key}'] = value
    for step, spec in (manifest.get('step_io') or {}).items():
        for direction in ['inputs', 'data_inputs', 'outputs']:
            for key, value in (spec.get(direction) or {}).items():
                if isinstance(value, str):
                    paths[f'step_io.{step}.{direction}.{key}'] = value
    return {key: object_status(Path(value)) for key, value in sorted(paths.items())}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Strict single-entry runner for Factor Forge Step2-6.')
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--start-step', default='3', help='2, 3, 3b, 4, 5, or 6')
    ap.add_argument('--end-step', default='6', help='2, 3, 3b, 4, 5, 6, or all')
    ap.add_argument('--factorforge-root', default=None)
    ap.add_argument('--branch-id', default=None)
    ap.add_argument('--manifest', default=None, help='Use an existing runtime manifest instead of creating a new one.')
    ap.add_argument('--skip-step3a', action='store_true', help='When starting at Step3, skip run_step3 and run only Step3B onward.')
    ap.add_argument('--skip-researcher-packets', action='store_true', help='Do not build Step6 researcher packet/dossier before Step6.')
    ap.add_argument('--apply-approved-revision', action='store_true', help='Apply a human-approved Step6 revision before running the requested step range.')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--proof-output', default=None)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    start = normalize_step(args.start_step, START_ALIASES)
    end = normalize_step(args.end_step, END_ALIASES)
    steps = step_slice(start, end)

    ctx = resolve_factorforge_context(args.factorforge_root)
    if args.manifest:
        manifest_path = Path(args.manifest).expanduser()
        manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else ctx.build_manifest(args.report_id, branch_id=args.branch_id)
    elif args.dry_run:
        manifest = ctx.build_manifest(args.report_id, branch_id=args.branch_id)
        manifest_path = Path(tempfile.gettempdir()) / f'factorforge_dry_run_manifest__{args.report_id}.json'
        write_json_atomic(manifest_path, manifest)
    else:
        manifest_path = ctx.write_manifest(args.report_id, branch_id=args.branch_id)
        manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else ctx.build_manifest(args.report_id, branch_id=args.branch_id)

    if args.proof_output:
        proof_path = Path(args.proof_output).expanduser()
    elif args.dry_run:
        proof_path = Path(tempfile.gettempdir()) / f'ultimate_run_report__{args.report_id}.json'
    else:
        proof_path = ctx.objects_root / 'runtime_context' / f'ultimate_run_report__{args.report_id}.json'
    env = os.environ.copy()
    env.pop('FACTORFORGE_ALLOW_DIRECT_STEP', None)
    env.pop('FACTORFORGE_ALLOW_LEGACY_STEP6_HANDOFF', None)
    env['FACTORFORGE_ROOT'] = str(ctx.factorforge_root)
    env['FACTORFORGE_ULTIMATE_RUN'] = '1'

    py = sys.executable
    commands: list[tuple[str, list[str]]] = []

    if args.apply_approved_revision:
        commands.append(('apply_approved_step6_revision', [py, 'skills/factor-forge-step6/scripts/apply_step6_iteration.py', '--manifest', str(manifest_path)]))

    if '2' in steps:
        commands.append(('run_step2', [py, 'skills/factor-forge-step2/scripts/run_step2.py', '--report-id', args.report_id]))
        commands.append(('validate_step2', [py, 'skills/factor-forge-step2/scripts/validate_step2.py', '--report-id', args.report_id]))

    if '3' in steps and not args.skip_step3a:
        commands.append(('build_runtime_manifest', [py, 'scripts/build_factorforge_runtime_context.py', '--report-id', args.report_id, '--write']))
        commands.append(('run_step3', [py, 'skills/factor-forge-step3/scripts/run_step3.py', '--manifest', str(manifest_path)]))
        commands.append(('validate_step3', [py, 'skills/factor-forge-step3/scripts/validate_step3.py', '--manifest', str(manifest_path)]))
    elif '3' in steps:
        commands.append(('build_runtime_manifest', [py, 'scripts/build_factorforge_runtime_context.py', '--report-id', args.report_id, '--write']))

    if '3b' in steps or ('3' in steps):
        commands.append(('run_step3b', [py, 'skills/factor-forge-step3/scripts/run_step3b.py', '--manifest', str(manifest_path)]))
        commands.append(('validate_step3b', [py, 'skills/factor-forge-step3/scripts/validate_step3b.py', '--manifest', str(manifest_path)]))

    if '4' in steps:
        commands.append(('run_step4', [py, 'skills/factor-forge-step4/scripts/run_step4.py', '--manifest', str(manifest_path)]))
        commands.append(('validate_step4', [py, 'skills/factor-forge-step4/scripts/validate_step4.py', '--report-id', args.report_id]))

    if '5' in steps:
        commands.append(('run_step5', [py, 'skills/factor-forge-step5/scripts/run_step5.py', '--manifest', str(manifest_path)]))
        commands.append(('validate_step5', [py, 'skills/factor-forge-step5/scripts/validate_step5.py', '--report-id', args.report_id]))

    if '6' in steps:
        if not args.skip_researcher_packets:
            commands.append(('build_researcher_dossier', [py, 'skills/factor-forge-researcher/scripts/build_researcher_dossier.py', '--report-id', args.report_id]))
            commands.append(('build_step6_researcher_packet', [py, 'skills/factor-forge-step6-researcher/scripts/build_researcher_packet.py', '--report-id', args.report_id]))
        commands.append(('run_step6', [py, 'skills/factor-forge-step6/scripts/run_step6.py', '--manifest', str(manifest_path)]))
        commands.append(('validate_step6', [py, 'skills/factor-forge-step6/scripts/validate_step6.py', '--report-id', args.report_id]))

    proof: dict[str, Any] = {
        'contract_version': 'factorforge_ultimate_wrapper_v1',
        'report_id': args.report_id,
        'started_at_utc': utc_now(),
        'finished_at_utc': None,
        'factorforge_root': str(ctx.factorforge_root),
        'repo_root': str(ctx.repo_root),
        'manifest_path': str(manifest_path),
        'start_step': start,
        'end_step': end,
        'requested_steps': steps,
        'dry_run': bool(args.dry_run),
        'status': 'RUNNING',
        'commands': [],
        'child_env_policy': {
            'FACTORFORGE_ULTIMATE_RUN': '1',
            'removed': ['FACTORFORGE_ALLOW_DIRECT_STEP', 'FACTORFORGE_ALLOW_LEGACY_STEP6_HANDOFF'],
        },
        'expected_artifacts_before': collect_expected_artifacts(manifest),
        'expected_artifacts_after': {},
        'failure': None,
        'usage_rule': 'This proof report is the only acceptable evidence for a claimed factor-forge-ultimate run. Agents must not replace formal Step4/5/6 execution by ad-hoc metrics or post-hoc object writing.',
    }
    write_json_atomic(proof_path, proof)

    for name, command in commands:
        result = run_command(name, command, cwd=ctx.repo_root, env=env, dry_run=args.dry_run)
        proof['commands'].append(asdict(result))
        proof['expected_artifacts_after'] = collect_expected_artifacts(manifest)
        proof['finished_at_utc'] = utc_now()
        if result.returncode != 0:
            proof['status'] = 'FAIL'
            proof['failure'] = {'command': name, 'returncode': result.returncode}
            write_json_atomic(proof_path, proof)
            print(f'[FAIL] {name} rc={result.returncode}')
            print(f'[PROOF] {proof_path}')
            return int(result.returncode or 1)
        write_json_atomic(proof_path, proof)

    proof['status'] = 'PASS'
    proof['finished_at_utc'] = utc_now()
    proof['expected_artifacts_after'] = collect_expected_artifacts(manifest)
    write_json_atomic(proof_path, proof)
    print(f'[PASS] factor-forge-ultimate wrapper completed for {args.report_id}')
    print(f'[MANIFEST] {manifest_path}')
    print(f'[PROOF] {proof_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
