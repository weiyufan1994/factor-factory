#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OBJECTS = REPO_ROOT / 'objects'
DEFAULT_OUTPUT = REPO_ROOT / 'knowledge' / 'retrieval' / 'factorforge_retrieval_index.jsonl'
DEFAULT_MANIFEST = REPO_ROOT / 'knowledge' / 'retrieval' / 'factorforge_retrieval_manifest.json'


def load_json(path: Path) -> dict[str, Any]:
    with path.open('r', encoding='utf-8') as fh:
        return json.load(fh)


def compact_text(parts: list[str]) -> str:
    return '\n'.join(part.strip() for part in parts if part and part.strip())


def make_factor_doc(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    rid = data['report_id']
    factor_id = data['factor_id']
    text = compact_text([
        f'Factor record for {factor_id} ({rid}).',
        f"decision={data.get('decision')} iteration_no={data.get('iteration_no')} run_status={data.get('run_status')} final_status={data.get('final_status')}",
        'headline_metrics=' + json.dumps(data.get('headline_metrics', {}), ensure_ascii=False),
        'strengths=' + '; '.join(data.get('strengths', [])),
        'weaknesses=' + '; '.join(data.get('weaknesses', [])),
        'risks=' + '; '.join(data.get('risks', [])),
    ])
    return {
        'id': f'factor_record::{rid}',
        'doc_type': 'factor_record',
        'report_id': rid,
        'factor_id': factor_id,
        'decision': data.get('decision'),
        'created_at_utc': data.get('created_at_utc'),
        'tags': ['factor_record', str(data.get('decision', 'unknown')), factor_id],
        'metadata': {
            'iteration_no': data.get('iteration_no'),
            'run_status': data.get('run_status'),
            'final_status': data.get('final_status'),
            'headline_metrics': data.get('headline_metrics', {}),
        },
        'source_path': str(path.resolve()),
        'text': text,
    }


def make_knowledge_doc(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    rid = data['report_id']
    factor_id = data['factor_id']
    text = compact_text([
        f'Knowledge record for {factor_id} ({rid}).',
        f"decision={data.get('decision')}",
        'success_patterns=' + '; '.join(data.get('success_patterns', [])),
        'failure_patterns=' + '; '.join(data.get('failure_patterns', [])),
        'modification_hypotheses=' + '; '.join(data.get('modification_hypotheses', [])),
    ])
    return {
        'id': f'knowledge_record::{rid}',
        'doc_type': 'knowledge_record',
        'report_id': rid,
        'factor_id': factor_id,
        'decision': data.get('decision'),
        'created_at_utc': data.get('created_at_utc'),
        'tags': ['knowledge_record', str(data.get('decision', 'unknown')), factor_id],
        'metadata': {
            'success_patterns': data.get('success_patterns', []),
            'failure_patterns': data.get('failure_patterns', []),
            'modification_hypotheses': data.get('modification_hypotheses', []),
        },
        'source_path': str(path.resolve()),
        'text': text,
    }


def make_iteration_doc(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    rid = data['report_id']
    factor_id = data['factor_id']
    judgment = data.get('research_judgment', {})
    evidence = data.get('evidence_summary', {})
    loop = data.get('loop_action', {})
    text = compact_text([
        f'Research iteration record for {factor_id} ({rid}).',
        f"iteration_no={data.get('iteration_no')} source_case_status={data.get('source_case_status')}",
        f"decision={judgment.get('decision')} thesis={judgment.get('thesis')}",
        'headline_metrics=' + json.dumps(evidence.get('headline_metrics', {}), ensure_ascii=False),
        'step5_lessons=' + '; '.join(evidence.get('step5_lessons', [])),
        'step5_next_actions=' + '; '.join(evidence.get('step5_next_actions', [])),
        'modification_targets=' + '; '.join(loop.get('modification_targets', [])),
        f"next_runner={loop.get('next_runner')} stop_reason={loop.get('stop_reason')}",
    ])
    return {
        'id': f'research_iteration::{rid}::{data.get("iteration_no")}',
        'doc_type': 'research_iteration',
        'report_id': rid,
        'factor_id': factor_id,
        'decision': judgment.get('decision'),
        'created_at_utc': None,
        'tags': ['research_iteration', str(judgment.get('decision', 'unknown')), factor_id],
        'metadata': {
            'iteration_no': data.get('iteration_no'),
            'source_case_status': data.get('source_case_status'),
            'backend_statuses': evidence.get('backend_statuses', {}),
            'headline_metrics': evidence.get('headline_metrics', {}),
            'modification_targets': loop.get('modification_targets', []),
        },
        'source_path': str(path.resolve()),
        'text': text,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description='Build a JSONL retrieval corpus from factor library / knowledge objects.')
    ap.add_argument('--output', default=str(DEFAULT_OUTPUT), help='JSONL output path')
    ap.add_argument('--manifest', default=str(DEFAULT_MANIFEST), help='Manifest output path')
    args = ap.parse_args()

    docs: list[dict[str, Any]] = []
    for path in sorted((OBJECTS / 'factor_library_all').glob('factor_record__*.json')):
        docs.append(make_factor_doc(path, load_json(path)))
    for path in sorted((OBJECTS / 'research_knowledge_base').glob('knowledge_record__*.json')):
        docs.append(make_knowledge_doc(path, load_json(path)))
    for path in sorted((OBJECTS / 'research_iteration_master').glob('research_iteration_master__*.json')):
        docs.append(make_iteration_doc(path, load_json(path)))

    output = Path(args.output).resolve()
    manifest = Path(args.manifest).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)

    with output.open('w', encoding='utf-8') as fh:
        for doc in docs:
            fh.write(json.dumps(doc, ensure_ascii=False) + '\n')
    print(f'[WRITE] {output}')

    summary = {
        'doc_count': len(docs),
        'doc_types': sorted({doc['doc_type'] for doc in docs}),
        'field_guide': {
            'id': 'stable retrieval id',
            'doc_type': 'factor_record | knowledge_record | research_iteration',
            'report_id': 'report identifier',
            'factor_id': 'factor family identifier',
            'decision': 'promote_official | iterate | reject | needs_human_review',
            'tags': 'keyword and routing tags for lexical / metadata retrieval',
            'metadata': 'structured fields for hybrid filtering',
            'text': 'embedding/full-text corpus body',
            'source_path': 'canonical source object path',
        },
    }
    manifest.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'[WRITE] {manifest}')


if __name__ == '__main__':
    main()
