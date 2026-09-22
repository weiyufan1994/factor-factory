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


def write_summary(report_id: str, payload: dict) -> Path:
    out = OBJ / 'research_iteration_master' / f'step6_controller_summary__{report_id}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--skip-step5', action='store_true')
    args = ap.parse_args()

    py = resolve_python()
    rid = args.report_id

    commands: list[tuple[str, list[str]]] = []
    start_step = '6' if args.skip_step5 else '5'
    commands.append((
        'run_factorforge_ultimate_step5_6',
        [
            py,
            str(REPO_ROOT / 'scripts' / 'run_factorforge_ultimate.py'),
            '--report-id',
            rid,
            '--start-step',
            start_step,
            '--end-step',
            '6',
        ],
    ))

    summary = {
        'report_id': rid,
        'runtime_root': str(FF),
        'entry_policy': 'official Step5/6 controller delegates to scripts/run_factorforge_ultimate.py; direct step scripts are debug-only.',
        'steps': [],
        'result': 'PASS',
    }

    for name, cmd in commands:
        result = run_checked(cmd)
        result['step'] = name
        summary['steps'].append(result)
        if result['returncode'] != 0:
            summary['result'] = 'FAIL'
            break

    out = write_summary(rid, summary)
    print(json.dumps({'result': summary['result'], 'summary_path': str(out)}, ensure_ascii=False, indent=2))
    if summary['result'] != 'PASS':
        raise SystemExit(1)
