#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(FF) not in sys.path:
    sys.path.append(str(FF))

from skills.factor_forge_step1.modules.report_ingestion.research_discipline import attach_step1_research_discipline  # type: ignore
from factor_factory.knowledge_context import retrieve_factor_knowledge_context

OBJ = FF / 'objects'


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {path}')


def build_step1_factor_knowledge_query(aim: dict) -> str:
    discipline = aim.get('research_discipline') or {}
    final_factor = aim.get('final_factor') or {}
    parts = [
        str(final_factor.get('name') or ''),
        str(final_factor.get('economic_logic') or ''),
        str(final_factor.get('behavioral_logic') or ''),
        str(final_factor.get('causal_chain') or ''),
        ' '.join(str(item) for item in final_factor.get('assembly_steps') or []),
        ' '.join(str(item) for item in aim.get('assembly_path') or []),
        json.dumps(discipline.get('economic_hypothesis') or {}, ensure_ascii=False),
        json.dumps(discipline.get('math_hypothesis_candidates') or [], ensure_ascii=False),
        str(discipline.get('initial_return_source_hypothesis') or ''),
        str(discipline.get('step1_random_object') or ''),
    ]
    return ' '.join(part for part in parts if part and part != '{}')


def summarize_factor_knowledge_context(context: dict) -> list[str]:
    lessons: list[str] = []
    for node in context.get('nodes') or []:
        node_id = node.get('id') or 'unknown_graph_node'
        status = ','.join(str(item) for item in node.get('research_status') or [])
        summary = str(node.get('summary') or '').strip()
        lesson = f'Graph prior {node_id}'
        if status:
            lesson += f' [{status}]'
        if summary:
            lesson += f': {summary[:260]}'
        lessons.append(lesson)
    return lessons


def attach_factor_knowledge_context(aim: dict) -> dict:
    query_text = build_step1_factor_knowledge_query(aim)
    try:
        context = retrieve_factor_knowledge_context(text=query_text, top_k=5)
    except Exception as exc:
        context = {
            'schema_version': 'factor_knowledge_context_v1',
            'node_count': 0,
            'nodes': [],
            'related_edges': [],
            'retrieval_error': str(exc),
            'query': {'text': query_text, 'top_k': 5},
        }
    knowledge_reference_contract = {
        'schema_version': 'factorforge_knowledge_reference_contract_v1',
        'source': 'factor_knowledge_graph' if (context.get('node_count') or 0) > 0 else 'cold_start_or_unavailable',
        'context_schema_version': context.get('schema_version'),
        'node_count': context.get('node_count') or 0,
        'edge_count': context.get('edge_count') or 0,
        'retrieval_error': context.get('retrieval_error'),
        'not_same_factor_unless_identity_matches': True,
    }
    enriched = dict(aim)
    discipline = dict(enriched.get('research_discipline') or {})
    learning = dict(enriched.get('learning_and_innovation') or {})
    prior_lessons = discipline.get('similar_case_lessons_imported') or learning.get('similar_case_lessons_imported') or []
    graph_lessons = summarize_factor_knowledge_context(context)
    merged_lessons = list(dict.fromkeys([
        *[str(item) for item in prior_lessons if str(item).strip()],
        *graph_lessons,
    ]))
    if not merged_lessons:
        merged_lessons = ['No similar prior case was imported from Step1/graph; treat this as a cold-start prior and write back lessons after Step6.']
    discipline['similar_case_lessons_imported'] = merged_lessons
    discipline['factor_knowledge_context'] = context
    discipline['knowledge_reference_contract'] = knowledge_reference_contract
    learning['similar_case_lessons_imported'] = merged_lessons
    learning['factor_knowledge_context'] = context
    learning['knowledge_reference_contract'] = knowledge_reference_contract
    enriched['research_discipline'] = discipline
    enriched['learning_and_innovation'] = learning
    enriched['knowledge_reference_contract'] = knowledge_reference_contract
    return enriched


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    args = ap.parse_args()
    rid = args.report_id
    path = OBJ / 'alpha_idea_master' / f'alpha_idea_master__{rid}.json'
    if not path.exists():
        raise SystemExit(f'STEP1_ALPHA_IDEA_MASTER_MISSING: {path}')
    aim = load_json(path)
    context = []
    for candidate in [
        OBJ / 'validation' / f'report_map_validation__{rid}__alpha_thesis.json',
        OBJ / 'validation' / f'report_map_validation__{rid}__challenger_alpha_thesis.json',
        OBJ / 'report_maps' / f'report_map__{rid}__primary.json',
    ]:
        if candidate.exists():
            context.append(load_json(candidate))
    enriched = attach_step1_research_discipline(aim, REPO_ROOT, *context)
    enriched = attach_factor_knowledge_context(enriched)
    write_json(path, enriched)
    handoff = OBJ / 'handoff' / f'handoff__{rid}.json'
    if handoff.exists():
        h = load_json(handoff)
        h.setdefault('objects', {})['alpha_idea_master'] = enriched
        h['research_discipline'] = enriched.get('research_discipline') or {}
        write_json(handoff, h)


if __name__ == '__main__':
    main()
