#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
RETRIEVAL_JSONL = REPO_ROOT / 'knowledge' / 'retrieval' / 'factorforge_retrieval_index.jsonl'
DEFAULT_EMBED = REPO_ROOT / 'knowledge' / 'retrieval' / 'factorforge_embeddings.npy'
DEFAULT_META = REPO_ROOT / 'knowledge' / 'retrieval' / 'factorforge_embedding_metadata.jsonl'
DEFAULT_MANIFEST = REPO_ROOT / 'knowledge' / 'retrieval' / 'factorforge_embedding_manifest.json'
DEFAULT_ENDPOINT = 'http://127.0.0.1:8008/v1/embeddings'


def load_docs() -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    if not RETRIEVAL_JSONL.exists():
        raise SystemExit(f'Missing retrieval corpus: {RETRIEVAL_JSONL}')
    for line in RETRIEVAL_JSONL.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line:
            docs.append(json.loads(line))
    return docs


def embed_texts(endpoint: str, texts: list[str]) -> np.ndarray:
    req = urllib.request.Request(
        endpoint,
        data=json.dumps({'input': texts}).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        payload = json.loads(resp.read().decode('utf-8'))
    vectors = [item['embedding'] for item in payload.get('data', [])]
    arr = np.asarray(vectors, dtype=np.float32)
    return arr


def main() -> None:
    ap = argparse.ArgumentParser(description='Build a local embedding index from factorforge_retrieval_index.jsonl via local BGE-M3 service.')
    ap.add_argument('--endpoint', default=DEFAULT_ENDPOINT)
    ap.add_argument('--output-embeddings', default=str(DEFAULT_EMBED))
    ap.add_argument('--output-metadata', default=str(DEFAULT_META))
    ap.add_argument('--output-manifest', default=str(DEFAULT_MANIFEST))
    ap.add_argument('--batch-size', type=int, default=8)
    args = ap.parse_args()

    docs = load_docs()
    texts = [str(doc.get('text') or '') for doc in docs]
    embeddings = []
    for start in range(0, len(texts), args.batch_size):
        batch = texts[start:start + args.batch_size]
        arr = embed_texts(args.endpoint, batch)
        embeddings.append(arr)
        print(f'[EMBED] batch={start}-{start + len(batch) - 1}')
    matrix = np.vstack(embeddings) if embeddings else np.zeros((0, 0), dtype=np.float32)

    emb_path = Path(args.output_embeddings).resolve()
    meta_path = Path(args.output_metadata).resolve()
    manifest_path = Path(args.output_manifest).resolve()
    emb_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    np.save(emb_path, matrix)
    print(f'[WRITE] {emb_path}')
    with meta_path.open('w', encoding='utf-8') as fh:
        for doc in docs:
            fh.write(json.dumps({
                'id': doc.get('id'),
                'doc_type': doc.get('doc_type'),
                'report_id': doc.get('report_id'),
                'factor_id': doc.get('factor_id'),
                'decision': doc.get('decision'),
                'source_path': doc.get('source_path'),
                'tags': doc.get('tags', []),
                'text': doc.get('text'),
            }, ensure_ascii=False) + '\n')
    print(f'[WRITE] {meta_path}')
    manifest = {
        'endpoint': args.endpoint,
        'embedding_count': int(matrix.shape[0]),
        'embedding_dim': int(matrix.shape[1]) if matrix.ndim == 2 and matrix.shape[0] else 0,
        'embedding_file': str(emb_path),
        'metadata_file': str(meta_path),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'[WRITE] {manifest_path}')


if __name__ == '__main__':
    main()
