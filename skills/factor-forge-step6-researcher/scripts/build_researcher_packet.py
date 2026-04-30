#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
OBJ = FF / 'objects'
EVAL = FF / 'evaluations'


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def file_info(path: Path) -> dict[str, Any]:
    return {
        'path': str(path),
        'exists': path.exists(),
        'size': path.stat().st_size if path.exists() else None,
    }


def compact_json(obj: Any, max_chars: int = 4000) -> Any:
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    if len(text) <= max_chars:
        return obj
    return {'truncated_json_preview': text[:max_chars], 'truncated': True}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--output', default=None)
    args = ap.parse_args()
    rid = args.report_id

    paths = {
        'factor_spec_master': OBJ / 'factor_spec_master' / f'factor_spec_master__{rid}.json',
        'factor_run_master': OBJ / 'factor_run_master' / f'factor_run_master__{rid}.json',
        'factor_case_master': OBJ / 'factor_case_master' / f'factor_case_master__{rid}.json',
        'factor_evaluation': OBJ / 'validation' / f'factor_evaluation__{rid}.json',
        'handoff_to_step6': OBJ / 'handoff' / f'handoff_to_step6__{rid}.json',
        'handoff_to_step5': OBJ / 'handoff' / f'handoff_to_step5__{rid}.json',
        'prior_research_iteration': OBJ / 'research_iteration_master' / f'research_iteration_master__{rid}.json',
        'prior_researcher_memo': OBJ / 'research_iteration_master' / f'researcher_memo__{rid}.json',
    }

    run_master = load_json(paths['factor_run_master'])
    backend_runs = (((run_master.get('evaluation_results') or {}).get('backend_runs')) or [])
    backend_payloads: dict[str, Any] = {}
    backend_artifacts: dict[str, list[dict[str, Any]]] = {}
    for item in backend_runs:
        backend = str(item.get('backend') or '')
        if not backend:
            continue
        payload_path = Path(str(item.get('payload_path') or EVAL / rid / backend / 'evaluation_payload.json'))
        if payload_path.exists():
            payload = load_json(payload_path)
            backend_payloads[backend] = compact_json(payload)
            artifacts = []
            for artifact in (payload.get('artifacts') or {}).values():
                if isinstance(artifact, str):
                    artifacts.append(file_info(Path(artifact)))
            backend_artifacts[backend] = artifacts
        else:
            backend_payloads[backend] = {'missing_payload_path': str(payload_path)}

    packet = {
        'report_id': rid,
        'factorforge_root': str(FF),
        'required_researcher_output': str(OBJ / 'research_iteration_master' / f'researcher_memo__{rid}.json'),
        'source_files': {key: file_info(path) for key, path in paths.items()},
        'objects': {
            key: compact_json(load_json(path))
            for key, path in paths.items()
            if path.exists() and key not in {'prior_researcher_memo'}
        },
        'backend_payloads': backend_payloads,
        'backend_artifacts': backend_artifacts,
        'suggested_checks': [
            'Inspect factor formula and intended direction.',
            'Compare IC/group diagnostics with native portfolio/account evidence.',
            'Open important png artifacts if present, especially NAV, benchmark-vs-strategy, turnover, quantile NAV/counts.',
            'Retrieve similar prior cases before final decision if retrieval index exists.',
            'Write researcher_memo JSON using the schema in factor-forge-step6-researcher/references/researcher-memo-schema.md.',
        ],
        'producer': 'factor-forge-step6-researcher.build_researcher_packet',
    }

    out = Path(args.output) if args.output else OBJ / 'research_iteration_master' / f'researcher_packet__{rid}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding='utf-8')
    print(str(out))


if __name__ == '__main__':
    main()
