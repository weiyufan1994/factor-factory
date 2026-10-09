"""Prepare the facts for an independent Step6 review; never author the review."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from factor_factory.runtime_context import resolve_factorforge_context


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


def build_researcher_packet(rid: str, *, workspace_root: Path | str | None = None) -> dict[str, Any]:
    root = resolve_factorforge_context(workspace_root).factorforge_root
    OBJ, EVAL = root / "objects", root / "evaluations"
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

    objects = {
        key: load_json(path)
        for key, path in paths.items()
        if path.exists() and key not in {'prior_researcher_memo'}
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
        if not payload_path.is_absolute():
            payload_path = root / payload_path
        if payload_path.exists():
            payload = load_json(payload_path)
            backend_payloads[backend] = compact_json(payload)
            artifacts = []
            for artifact in (payload.get('artifacts') or {}).values():
                if isinstance(artifact, str):
                    artifact_path = Path(artifact)
                    artifacts.append(file_info(artifact_path if artifact_path.is_absolute() else root / artifact_path))
            backend_artifacts[backend] = artifacts
        else:
            backend_payloads[backend] = {'missing_payload_path': str(payload_path)}

    packet = {
        'report_id': rid,
        'factorforge_root': str(root),
        'required_researcher_output': str(OBJ / 'research_iteration_master' / f'researcher_memo__{rid}.json'),
        'source_files': {key: file_info(path) for key, path in paths.items()},
        'objects': {key: compact_json(value) for key, value in objects.items()},
        'backend_payloads': backend_payloads,
        'backend_artifacts': backend_artifacts,
        'suggested_checks': [
            'Inspect factor formula and intended direction.',
            'Compare IC/group diagnostics with native portfolio/account evidence.',
            'Open important png artifacts if present, especially NAV, benchmark-vs-strategy, turnover, quantile NAV/counts.',
            'Retrieve similar prior cases before final decision if retrieval index exists.',
            'Write researcher_memo JSON using skills/factor-forge-step6/references/researcher-memo-schema.md.',
        ],
        'producer': 'factor-forge-step6-researcher.build_researcher_packet',
    }
    return packet


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)
    packet = build_researcher_packet(args.report_id)
    out = Path(args.output) if args.output else Path(packet["required_researcher_output"]).with_name(f"researcher_packet__{args.report_id}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out))


if __name__ == "__main__":
    main()
