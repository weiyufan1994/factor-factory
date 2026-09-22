#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX = REPO_ROOT / 'knowledge' / 'retrieval' / 'factorforge_retrieval_index.jsonl'
EMBEDDINGS = REPO_ROOT / 'knowledge' / 'retrieval' / 'factorforge_embeddings.npy'
EMBED_META = REPO_ROOT / 'knowledge' / 'retrieval' / 'factorforge_embedding_metadata.jsonl'
DEFAULT_ENDPOINT = 'http://127.0.0.1:8008/v1/embeddings'


def tokenize(text: str) -> list[str]:
    return re.findall(r'[a-zA-Z_]{3,}|[\u4e00-\u9fff]{1,}', text.lower())


def load_docs() -> list[dict]:
    docs = []
    if not INDEX.exists():
        return docs
    for line in INDEX.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line:
            docs.append(json.loads(line))
    return docs


def load_embedding_docs() -> list[dict[str, Any]]:
    docs = []
    if not EMBED_META.exists():
        return docs
    for line in EMBED_META.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line:
            docs.append(json.loads(line))
    return docs


def embed_query(endpoint: str, text: str) -> np.ndarray:
    req = urllib.request.Request(
        endpoint,
        data=json.dumps({'input': [text]}).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode('utf-8'))
    vec = np.asarray(payload['data'][0]['embedding'], dtype=np.float32)
    return vec


def main() -> None:
    ap = argparse.ArgumentParser(description='Query the FactorForge retrieval JSONL with lightweight lexical + metadata scoring.')
    ap.add_argument('--query', required=True)
    ap.add_argument('--factor-id')
    ap.add_argument('--decision')
    ap.add_argument('--top-k', type=int, default=5)
    ap.add_argument('--use-embeddings', action='store_true')
    ap.add_argument('--endpoint', default=DEFAULT_ENDPOINT)
    args = ap.parse_args()

    q_tokens = set(tokenize(args.query))
    rows = []
    for doc in load_docs():
        if args.factor_id and str(doc.get('factor_id')) != args.factor_id:
            continue
        if args.decision and str(doc.get('decision')) != args.decision:
            continue
        d_tokens = set(tokenize(str(doc.get('text') or '')))
        overlap = q_tokens & d_tokens
        score = float(len(overlap))
        if args.factor_id and str(doc.get('factor_id')) == args.factor_id:
            score += 5.0
        if args.decision and str(doc.get('decision')) == args.decision:
            score += 1.0
        if score <= 0:
            continue
        rows.append({
            'score': round(score, 4),
            'report_id': doc.get('report_id'),
            'factor_id': doc.get('factor_id'),
            'doc_type': doc.get('doc_type'),
            'decision': doc.get('decision'),
            'overlap_terms': sorted(overlap)[:12],
            'source_path': doc.get('source_path'),
            'snippet': str(doc.get('text') or '')[:280],
        })

    if args.use_embeddings and EMBEDDINGS.exists() and EMBED_META.exists():
        emb_docs = load_embedding_docs()
        matrix = np.load(EMBEDDINGS)
        qvec = embed_query(args.endpoint, args.query)
        sims = matrix @ qvec
        emb_rows = []
        for idx, score in enumerate(sims.tolist()):
            doc = emb_docs[idx]
            if args.factor_id and str(doc.get('factor_id')) != args.factor_id:
                continue
            if args.decision and str(doc.get('decision')) != args.decision:
                continue
            emb_rows.append({
                'score': round(float(score), 4),
                'report_id': doc.get('report_id'),
                'factor_id': doc.get('factor_id'),
                'doc_type': doc.get('doc_type'),
                'decision': doc.get('decision'),
                'source_path': doc.get('source_path'),
                'overlap_terms': [],
                'snippet': str(doc.get('text') or '')[:280],
                'retrieval_mode': 'embedding',
            })
        emb_rows.sort(key=lambda x: (-x['score'], str(x.get('report_id') or '')))
        print(json.dumps({'query': args.query, 'results': emb_rows[: args.top_k]}, ensure_ascii=False, indent=2))
        return
    rows.sort(key=lambda x: (-x['score'], str(x.get('report_id') or '')))
    print(json.dumps({'query': args.query, 'results': rows[: args.top_k]}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
