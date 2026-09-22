"""Build an explicitly requested local semantic index; never downloads models."""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factor_factory.semantic_knowledge_retrieval import build_semantic_index, local_bge_encoder, refresh_configured_index

__all__ = ["build_semantic_index"]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root'); ap.add_argument('--corpus'); ap.add_argument('--output'); ap.add_argument('--model-path')
    a=ap.parse_args()
    if a.root:
        print(json.dumps(refresh_configured_index(Path(a.root)), ensure_ascii=False))
        return
    if not (a.corpus and a.output and a.model_path):
        ap.error('use --root or --corpus --output --model-path')
    rows=[json.loads(x) for x in Path(a.corpus).read_text(encoding='utf-8').splitlines() if x.strip()]
    print(json.dumps(build_semantic_index(rows, local_bge_encoder(a.model_path), Path(a.output)), ensure_ascii=False))
if __name__ == '__main__': main()
