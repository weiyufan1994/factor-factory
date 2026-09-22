"""Local dense recall of caller-visible advisory text, never economic evidence."""
from __future__ import annotations
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable

MODEL_ID = "BAAI/bge-m3"


def graph_documents(node_index: Path, repo_root: Path) -> list[dict[str, Any]]:
    """Only the graph explicitly selected by the post-source advisory caller."""
    from factor_factory.knowledge_context import load_jsonl, resolve_graph_node_path, compact_node
    documents = []
    for row in load_jsonl(node_index):
        raw_path = row.get("source_node_path")
        if raw_path:
            path = resolve_graph_node_path(raw_path, repo_root=repo_root, graph_root=node_index.parent)
            if path.is_symlink() or not path.is_file():
                raise ValueError("unavailable_graph_source")
            full = json.loads(path.read_text())
        else:
            full = row
        if full.get("id") != row.get("id"):
            raise ValueError("graph_identity_mismatch")
        compact = compact_node(full, row, [])
        if raw_path:
            compact["source_node_path"] = str(path.resolve())
        body = "\n".join([str(full.get("title") or ""), str(full.get("summary") or ""),
                           json.dumps(full.get("mechanism") or {}, ensure_ascii=False)])
        documents.append({"id": full["id"], "search_text": body, "node": compact})
    return documents


def refresh_configured_index(runtime_root: Path) -> dict[str, Any]:
    """Rebuild only this root's enabled derivative cache, without research work."""
    root = Path(runtime_root).resolve()
    directory = root / "knowledge/retrieval"
    config_path = directory / "semantic_config.json"
    if not directory.resolve().is_relative_to(root) or config_path.is_symlink():
        raise ValueError("semantic_configuration_outside_root")
    if not config_path.is_file():
        return {"status": "SKIPPED", "reason": "unconfigured"}
    config = json.loads(config_path.read_text())
    if config.get("enabled") is not True:
        return {"status": "SKIPPED", "reason": "disabled"}
    index_path = directory / config.get("index_path", "factorforge_semantic_index.json")
    if index_path.is_symlink() or not index_path.resolve().is_relative_to(directory.resolve()):
        raise ValueError("semantic_index_outside_root")
    corpus = directory / "factorforge_retrieval_index.jsonl"
    rows = [json.loads(line) for line in corpus.read_text().splitlines() if line.strip()]
    # Operational episodes remain searchable lexically, not method/economic priors.
    rows = [row for row in rows if row.get("doc_type") != "research_episode"]
    graph = root / "knowledge/因子工厂/graph/factor_knowledge_nodes.jsonl"
    if graph.is_file():
        rows.extend(graph_documents(graph, root))
    return {"status": "REFRESHED", **build_semantic_index(
        rows, configured_encoder(config), index_path, model_id=config.get("model_id", MODEL_ID))}


def search_text(row: dict[str, Any]) -> str:
    return str(row.get("search_text") or row.get("text") or row.get("summary") or "")


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def local_bge_encoder(model_path: str, *, threads: int = 2, max_length: int = 512):
    """Bounded CPU inference; cache one model per process, never download."""
    path = Path(model_path).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError("model_path_must_be_local_directory")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(max(1, min(int(threads), 2)))
    model = SentenceTransformer(str(path), device="cpu", local_files_only=True,
                                trust_remote_code=False)
    model.max_seq_length = max(32, min(int(max_length), 512))

    def encode(texts):
        if not texts:
            return []
        return model.encode(list(texts), batch_size=2, normalize_embeddings=True,
                            convert_to_numpy=True, show_progress_bar=False).tolist()
    return encode


def configured_encoder(config: dict[str, Any]):
    """Optional isolated Python keeps torch out of research environments."""
    kwargs = {"threads": int(config.get("threads", 2)),
              "max_length": int(config.get("max_length", 512))}
    model_path = str(config["model_path"])
    python = str(config.get("python_path") or sys.executable)
    if Path(python).resolve() == Path(sys.executable).resolve():
        return local_bge_encoder(model_path, **kwargs)

    def encode(texts):
        env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                   TOKENIZERS_PARALLELISM="false", OMP_NUM_THREADS="2")
        result = subprocess.run(
            [python, str(Path(__file__).resolve()), "--encode", model_path,
             str(kwargs["threads"]), str(kwargs["max_length"])],
            input=json.dumps(list(texts)), text=True, capture_output=True,
            timeout=60, check=True, env=env,
        )
        return json.loads(result.stdout)
    return encode


def _vector(raw: Any, dimension: int | None = None) -> list[float]:
    values = [float(x) for x in raw]
    if not values or (dimension is not None and len(values) != dimension):
        raise ValueError("vector_dimension_mismatch")
    if not all(math.isfinite(x) for x in values):
        raise ValueError("nonfinite_vector")
    norm = math.sqrt(sum(x * x for x in values))
    if norm <= 0:
        raise ValueError("zero_vector")
    return [x / norm for x in values]


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    content = json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("unsafe_semantic_index")
    fd, name = tempfile.mkstemp(prefix=".semantic-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def build_semantic_index(rows: Iterable[dict[str, Any]], encoder: Callable,
                         output: Path, *, model_id: str = MODEL_ID) -> dict[str, Any]:
    rows = list(rows)
    ids = [str(row.get("id") or "") for row in rows]
    if any(not key for key in ids) or len(set(ids)) != len(ids):
        raise ValueError("invalid_or_duplicate_semantic_id")
    texts = [search_text(row) for row in rows]
    if any(not value.strip() for value in texts):
        raise ValueError("missing_semantic_text")
    vectors = list(encoder(texts)) if rows else []
    if len(vectors) != len(rows):
        raise ValueError("encoder_row_count_mismatch")
    dimension = len(vectors[0]) if vectors else 0
    payload = {
        "schema": "factorforge_semantic_index_v1", "model_id": model_id,
        "dimension": dimension, "row_count": len(rows),
        "rows": [{"id": key, "text_sha256": text_hash(text),
                  "vector": _vector(vector, dimension)}
                 for key, text, vector in zip(ids, texts, vectors)],
    }
    _atomic_json(Path(output), payload)
    return {"path": str(output), "row_count": len(rows), "model_id": model_id,
            "dimension": dimension, "available": True}


def unavailable(reason: str) -> dict[str, Any]:
    return {"semantic_available": False, "semantic_used": False,
            "fallback": reason, "hits": []}


def retrieve_semantic(query: str, index: Path, encoder: Callable, *, top_k: int = 10,
                      allowed_ids: set[str] | None = None, model_id: str = MODEL_ID,
                      expected_text_hashes: dict[str, str] | None = None,
                      min_similarity: float = 0.35) -> dict[str, Any]:
    if not query.strip():
        return unavailable("empty_query")
    try:
        if index.is_symlink():
            return unavailable("unsafe_index")
        payload = json.loads(index.read_text())
        if payload.get("model_id") != model_id:
            return unavailable("stale_model")
        if payload.get("schema") != "factorforge_semantic_index_v1":
            return unavailable("invalid_index_schema")
        rows = payload["rows"]
        if len(rows) != payload["row_count"]:
            return unavailable("invalid_row_count")
        keyed = {row["id"]: row for row in rows}
        if len(keyed) != len(rows):
            return unavailable("duplicate_semantic_id")
        expected = expected_text_hashes or {}
        visible = allowed_ids if allowed_ids is not None else set(keyed)
        if any(key not in keyed or keyed[key]["text_sha256"] != digest
               for key, digest in expected.items() if key in visible):
            return unavailable("stale_source_text")
        selected = [row for key, row in keyed.items() if key in visible]
        if not selected:
            return unavailable("no_visible_candidates")
        dimension = payload["dimension"]
        vectors = [_vector(row["vector"], dimension) for row in selected]
        query_vectors = list(encoder([query]))
        if len(query_vectors) != 1:
            raise ValueError("query_row_count_mismatch")
        qv = _vector(query_vectors[0], dimension)
        hits = []
        for row, vector in zip(selected, vectors):
            score = sum(a * b for a, b in zip(qv, vector))
            if score >= min_similarity:
                hits.append({"id": row["id"], "similarity": score,
                             "semantic_only": True, "similarity_is_evidence": False})
        hits.sort(key=lambda row: (-row["similarity"], row["id"]))
        return {"semantic_available": True, "semantic_used": True, "fallback": None,
                "model_id": model_id, "hits": hits[:max(0, top_k)]}
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, ImportError, subprocess.SubprocessError):
        return unavailable("index_or_encoder_unavailable")


def retrieve_configured(query: str, rows: list[dict[str, Any]], config_path: Path,
                        *, top_k: int = 10) -> dict[str, Any]:
    if os.environ.get("FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL") == "1":
        return unavailable("explicitly_disabled")
    try:
        if not config_path.is_file() or config_path.is_symlink():
            return unavailable("unconfigured")
        config = json.loads(config_path.read_text())
        if config.get("enabled") is not True:
            return unavailable("disabled")
        root = config_path.parent.resolve()
        index = root / config.get("index_path", "factorforge_semantic_index.json")
        if index.is_symlink() or not index.resolve().is_relative_to(root):
            return unavailable("index_outside_retrieval_root")
        texts = {str(row["id"]): text_hash(search_text(row)) for row in rows}
        def encode(values):
            return configured_encoder(config)(values)
        return retrieve_semantic(query, index, encode, top_k=top_k,
                                 model_id=config.get("model_id", MODEL_ID),
                                 allowed_ids=set(texts), expected_text_hashes=texts,
                                 min_similarity=float(config.get("min_similarity", 0.35)))
    except (OSError, ValueError, KeyError, TypeError):
        return unavailable("invalid_configuration")


if __name__ == "__main__" and len(sys.argv) == 5 and sys.argv[1] == "--encode":
    encoder = local_bge_encoder(sys.argv[2], threads=int(sys.argv[3]), max_length=int(sys.argv[4]))
    print(json.dumps(encoder(json.load(sys.stdin)), allow_nan=False))
