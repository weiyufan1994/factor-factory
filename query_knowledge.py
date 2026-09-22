#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
from factor_factory.knowledge_context import retrieve_factor_knowledge_context
from factor_factory.knowledge_reference import build_knowledge_reference_contract
ROOT = Path(__file__).resolve().parent
VAULT = ROOT / 'knowledge'
GRAPH = VAULT / '因子工厂' / 'graph'
TAXONOMY = VAULT / '因子工厂' / 'taxonomy' / 'factor_taxonomy_v1.json'
def main() -> None:
    ap = argparse.ArgumentParser(description='Offline Factor Forge knowledge preview (advisory only).')
    ap.add_argument('--query', required=True)
    ap.add_argument('--top-k', type=int, default=3)
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()
    context = retrieve_factor_knowledge_context(text=args.query, top_k=args.top_k, node_index=GRAPH / 'factor_knowledge_nodes.jsonl', edge_index=GRAPH / 'factor_knowledge_edges.jsonl', taxonomy=TAXONOMY, repo_root=ROOT, graph_root=GRAPH)
    reference = build_knowledge_reference_contract(repo_root=ROOT, knowledge_root=VAULT, query_text=args.query, producer='knowledge_preview_cli', top_k=args.top_k)
    payload = {'preview_only': True, 'advisory_only': True, 'query': args.query, 'nodes': context.get('nodes', []), 'related_edges': context.get('related_edges', []), 'reference': reference, 'note': 'This is a knowledge-module preview; formal research still requires the existing Ultimate and governed data environment.'}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print('Factor Forge knowledge preview (advisory-only)')
        print('Query:', args.query or '<empty>')
        print('Hits:', reference.get('hit_count', 0))
        for node in (payload['nodes'] or [])[:args.top_k]:
            print(f"- {node.get('title') or node.get('id')} [{','.join(node.get('research_status') or [])}]")
            if node.get('summary'):
                print('  ', node['summary'])
            for guidance in (node.get('reuse_guidance') or [])[:3]:
                print('  Reuse / boundary:', guidance)
            for relation in (node.get('relations') or [])[:4]:
                print('  Related:', relation.get('target'), '-', relation.get('note'))
            for source in (node.get('source_paths') or [])[:2]:
                print('  Source:', source)
        print('Formal research still requires the existing Ultimate and governed data environment.')
if __name__ == '__main__':
    main()
