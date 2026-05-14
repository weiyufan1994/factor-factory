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

APPENDIX_VERSION = 'factorforge_revision_council_derivation_appendix_v1'


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {path}')


def write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding='utf-8')
    print(f'[WRITE] {path}')


def nonempty_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def resolve_source_paths(summary: dict[str, Any], council_dir: Path) -> list[Path]:
    paths: list[Path] = []
    if summary.get('selection_source') == 'agentic_results':
        for row in nonempty_list(summary.get('valid_agent_results')):
            raw = row.get('path') if isinstance(row, dict) else None
            if raw:
                paths.append(Path(raw).expanduser())
    else:
        for row in nonempty_list(summary.get('candidate_proposals')):
            raw = row.get('path') if isinstance(row, dict) else None
            if raw:
                paths.append(Path(raw).expanduser())
        if not paths:
            paths.extend(sorted(council_dir.glob('proposal__*.json')))
    return paths


def build_agent_section(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    public = payload.get('public_derivation_record') or payload.get('derivation_record') or {}
    if not isinstance(public, dict):
        public = {}
    laws = payload.get('candidate_revision_laws') or payload.get('revision_hypotheses') or []
    if not isinstance(laws, list):
        laws = []
    return {
        'source_path': str(path),
        'agent_role': payload.get('agent_role') or payload.get('role'),
        'task_id': payload.get('task_id'),
        'producer': payload.get('producer'),
        'research_depth': payload.get('research_depth'),
        'proposal_generation_mode': payload.get('proposal_generation_mode'),
        'research_question': public.get('research_question') or payload.get('research_question'),
        'assumptions': nonempty_list(public.get('assumptions')),
        'mathematical_objects': nonempty_list(public.get('mathematical_objects')),
        'selected_tools': nonempty_list(public.get('selected_tools')),
        'formula_claims': nonempty_list(public.get('formula_claims')),
        'derivation_steps_summary': nonempty_list(public.get('derivation_steps_summary')),
        'limiting_cases': nonempty_list(public.get('limiting_cases')),
        'falsification_tests': nonempty_list(public.get('falsification_tests') or payload.get('falsification_tests')),
        'kill_criteria': nonempty_list(public.get('kill_criteria') or payload.get('kill_criteria')),
        'candidate_revision_laws': laws,
        'overclaim_guard': public.get('overclaim_guard') or payload.get('overclaim_guard'),
    }


def validate_appendix(appendix: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if appendix.get('canonical_write_permission') is not False:
        reasons.append('canonical_write_permission_must_be_false')
    if appendix.get('execution_allowed_by_default') is not False:
        reasons.append('execution_allowed_by_default_must_be_false')
    sections = appendix.get('agent_derivations') or []
    if not sections:
        reasons.append('agent_derivations_missing')
    for idx, section in enumerate(sections):
        prefix = f'agent_derivations[{idx}]'
        for key in ['assumptions', 'mathematical_objects', 'selected_tools', 'formula_claims', 'derivation_steps_summary', 'falsification_tests', 'kill_criteria']:
            if not nonempty_list(section.get(key)):
                reasons.append(f'{prefix}.{key}_missing')
        for tool_idx, tool in enumerate(nonempty_list(section.get('selected_tools'))):
            if isinstance(tool, dict) and not str(tool.get('why_selected') or '').strip():
                reasons.append(f'{prefix}.selected_tools[{tool_idx}].why_selected_missing')
        for claim_idx, claim in enumerate(nonempty_list(section.get('formula_claims'))):
            if isinstance(claim, dict) and not str(claim.get('formula_or_relation') or '').strip():
                reasons.append(f'{prefix}.formula_claims[{claim_idx}].formula_or_relation_missing')
    return reasons


def bullet_lines(items: list[Any], *, key: str | None = None, limit: int | None = None) -> list[str]:
    rows = []
    for item in items[:limit] if limit else items:
        if isinstance(item, dict):
            if key and item.get(key):
                rows.append(f'- {item.get(key)}')
            elif item.get('statement'):
                rows.append(f"- {item.get('statement')}")
            elif item.get('claim'):
                rows.append(f"- {item.get('claim')}: `{item.get('formula_or_relation') or 'formula missing'}`")
            elif item.get('tool'):
                rows.append(f"- `{item.get('tool')}`: {item.get('why_selected') or 'why_selected missing'}")
            elif item.get('law_statement'):
                rows.append(f"- {item.get('law_statement')} `{item.get('mathematical_relation') or ''}`".rstrip())
            else:
                rows.append(f'- `{json.dumps(item, ensure_ascii=False)}`')
        else:
            rows.append(f'- {item}')
    return rows or ['- missing']


def render_markdown(appendix: dict[str, Any]) -> str:
    lines = [
        f"# Council Derivation Appendix: {appendix['report_id']}",
        '',
        f"Status: `{appendix['status']}`  ",
        f"Selection source: `{appendix.get('selection_source')}`  ",
        f"Created: `{appendix['created_at_utc']}`",
        '',
        'This appendix is public derivation evidence only. It is not hidden chain-of-thought, not code approval, and not permission to write Step3B handoff/generated code/official records.',
        '',
    ]
    for section in appendix.get('agent_derivations') or []:
        role = section.get('agent_role') or 'unknown_agent'
        lines.extend([
            f"## {role}",
            '',
            f"Research question: {section.get('research_question') or 'missing'}",
            '',
            '### Selected Tools',
            *bullet_lines(section.get('selected_tools') or [], limit=8),
            '',
            '### Mathematical Objects',
            *bullet_lines(section.get('mathematical_objects') or [], key='meaning', limit=10),
            '',
            '### Formula Claims',
            *bullet_lines(section.get('formula_claims') or [], limit=10),
            '',
            '### Derivation Steps',
            *bullet_lines(section.get('derivation_steps_summary') or [], limit=10),
            '',
            '### Limiting Cases',
            *bullet_lines(section.get('limiting_cases') or [], key='case', limit=10),
            '',
            '### Candidate Revision Laws',
            *bullet_lines(section.get('candidate_revision_laws') or [], limit=10),
            '',
            '### Falsification Tests',
            *bullet_lines(section.get('falsification_tests') or [], limit=10),
            '',
            '### Kill Criteria',
            *bullet_lines(section.get('kill_criteria') or [], limit=10),
            '',
        ])
    return '\n'.join(lines).rstrip() + '\n'


def main() -> int:
    parser = argparse.ArgumentParser(description='Build public derivation appendix from selected Revision Council outputs.')
    parser.add_argument('--report-id', required=True)
    args = parser.parse_args()
    rid = args.report_id
    council_dir = OBJ / 'research_iteration_master' / 'revision_council' / rid
    summary_path = council_dir / f'revision_council_summary__{rid}.json'
    if not summary_path.exists():
        raise SystemExit(f'BLOCK_COUNCIL_DERIVATION_APPENDIX_SUMMARY_MISSING: {summary_path}')
    summary = load_json(summary_path)
    source_paths = resolve_source_paths(summary, council_dir)
    sections = []
    missing = []
    for path in source_paths:
        if not path.exists():
            missing.append(str(path))
            continue
        sections.append(build_agent_section(path))
    appendix = {
        'appendix_version': APPENDIX_VERSION,
        'report_id': rid,
        'created_at_utc': utc_now(),
        'status': 'public_derivation_appendix',
        'selection_source': summary.get('selection_source'),
        'canonical_write_permission': False,
        'execution_allowed_by_default': False,
        'human_approval_required_before_step3b': True,
        'source_summary_path': str(summary_path),
        'source_paths': [str(p) for p in source_paths],
        'missing_source_paths': missing,
        'agent_derivations': sections,
        'safety_policy': {
            'no_hidden_chain_of_thought': True,
            'public_derivation_record_only': True,
            'forbidden_writes': [
                'objects/handoff/handoff_to_step3b__<report_id>.json',
                'generated_code/<report_id>/',
                'objects/factor_library_official/factor_record__<report_id>.json',
                'data/clean/',
            ],
        },
    }
    reasons = validate_appendix(appendix)
    if missing:
        reasons.append('source_paths_missing')
    if reasons:
        raise SystemExit('BLOCK_COUNCIL_DERIVATION_APPENDIX_INVALID: ' + '; '.join(reasons))
    json_path = council_dir / f'council_derivation_appendix__{rid}.json'
    md_path = council_dir / f'council_derivation_appendix__{rid}.md'
    write_json(json_path, appendix)
    write_text(md_path, render_markdown(appendix))
    print(json.dumps({'report_id': rid, 'result': 'PASS', 'json_path': str(json_path), 'markdown_path': str(md_path), 'agent_derivation_count': len(sections)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
