#!/usr/bin/env python3
"""Build a portable, read-only Factor Forge knowledge preview ZIP."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

try:  # Package import for tests and callers importing `scripts.*`.
    from scripts.build_factorforge_retrieval_index import make_knowledge_doc, active_workspace_exports
except ModuleNotFoundError:  # Direct `python3 scripts/build_...py` entry.
    from build_factorforge_retrieval_index import make_knowledge_doc, active_workspace_exports


PACKAGE_FILES = (
    "factor_factory/__init__.py",
    "factor_factory/knowledge_context.py",
    "factor_factory/knowledge_reference.py",
    "factor_factory/semantic_knowledge_retrieval.py",
    "factor_factory/research_workspace.py",
    "factor_factory/research_org/contracts.py",
)
GRAPH_FILES = (
    "knowledge/因子工厂/graph/factor_knowledge_nodes.jsonl",
    "knowledge/因子工厂/graph/factor_knowledge_edges.jsonl",
    "knowledge/因子工厂/taxonomy/factor_taxonomy_v1.json",
)
CLI = "query_knowledge.py"
WORKSPACE_EXPERIENCE_EXPORTS = Path("knowledge/因子工厂/workspace_experience_exports")
PREVIEW_RETRIEVAL_INDEX = Path("knowledge/retrieval/factorforge_retrieval_index.jsonl")


def _scrub(value: object, key: str = "") -> object:
    lowered = key.casefold()
    metric_key = (
        lowered in {"key_metrics", "metrics", "metric", "headline_metrics"}
        or "sharpe" in lowered or "drawdown" in lowered or "rank_ic" in lowered
        or "turnover" in lowered or "annual_return" in lowered
        or lowered.endswith("_return") or lowered in {"oos_rows", "oos_dates", "oos_tickers"}
    )
    if metric_key:
        return None
    if isinstance(value, dict):
        return {k: cleaned for k, raw in value.items() if (cleaned := _scrub(raw, str(k))) is not None}
    if isinstance(value, list):
        return [cleaned for raw in value if (cleaned := _scrub(raw, key)) is not None]
    if isinstance(value, str):
        if value.startswith("/"):
            return "<private-path-redacted>"
        return re.sub(r"/(?:Users|home|private|tmp|var)/[^\s,;]+", "<private-path-redacted>", value)
    return value


def _copy_scrubbed_json(source: Path, target: Path) -> None:
    payload = json.loads(source.read_text(encoding="utf-8"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_scrub(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _copy_scrubbed_jsonl(source: Path, target: Path) -> None:
    rows = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(_scrub(json.loads(line)))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _assert_graph_projection(staging: Path) -> None:
    graph = staging / "knowledge/因子工厂/graph"
    index_ids = {
        str(json.loads(line).get("id"))
        for line in (graph / "factor_knowledge_nodes.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    node_ids = {
        str(json.loads(path.read_text(encoding="utf-8")).get("id"))
        for path in (graph / "nodes").glob("*.json")
    }
    if index_ids != node_ids:
        raise ValueError("public graph node index and node files are inconsistent; rebuild the source graph first")


def _write_workspace_experience_preview_index(source_root: Path, staging: Path) -> int:
    """Project only explicit local candidate exports into the offline index."""
    exports = source_root / WORKSPACE_EXPERIENCE_EXPORTS
    if not exports.exists():
        return 0
    if exports.is_symlink() or not exports.is_dir():
        raise FileNotFoundError(f"unsafe workspace experience export directory: {exports}")
    docs: list[dict[str, object]] = []
    for source, payload in active_workspace_exports(exports):
        doc = make_knowledge_doc(source, payload)
        # Never carry the originating workspace/host path into a portable ZIP.
        preview_ref = Path("knowledge/experience_previews") / source.name
        doc["source_path"] = preview_ref.as_posix()
        doc["workspace_experience_export"] = {
            "export_status": payload["export_status"],
            "advisory_only": True,
            "same_factor_not_generalized": True,
            "source_record_relative_ref": payload.get("source_record_relative_ref"),
            "original_record_included_or_verified": False,
            "preview_only": True,
        }
        projected = _scrub(doc)
        docs.append(projected)
        target = staging / preview_ref
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(projected, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    if docs:
        target = staging / PREVIEW_RETRIEVAL_INDEX
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "".join(json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n" for doc in docs),
            encoding="utf-8",
        )
    return len(docs)


def _write_cli(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
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
""",
        encoding="utf-8",
    )


def build_preview(*, source_root: Path, output: Path) -> Path:
    source_root = source_root.expanduser().resolve()
    output = output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"refuse to overwrite existing output: {output}")
    with tempfile.TemporaryDirectory(prefix="factorforge-knowledge-preview-") as temp:
        staging = Path(temp) / "factorforge-knowledge-preview"
        staging.mkdir()
        for relative in PACKAGE_FILES:
            source = source_root / relative
            if not source.is_file() or source.is_symlink():
                raise FileNotFoundError(f"required preview source missing or unsafe: {source}")
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        for relative in GRAPH_FILES:
            source = source_root / relative
            if not source.is_file() or source.is_symlink():
                raise FileNotFoundError(f"required preview source missing or unsafe: {source}")
            target = staging / relative
            if relative.endswith(".jsonl"):
                _copy_scrubbed_jsonl(source, target)
            else:
                _copy_scrubbed_json(source, target)
        node_source_dir = source_root / "knowledge/因子工厂/graph/nodes"
        for source in sorted(node_source_dir.glob("*.json")):
            if source.is_symlink():
                raise FileNotFoundError(f"unsafe symlink preview source: {source}")
            target = staging / "knowledge/因子工厂/graph/nodes" / source.name
            _copy_scrubbed_json(source, target)
        _assert_graph_projection(staging)
        _write_workspace_experience_preview_index(source_root, staging)
        minimal_init = staging / "factor_factory/research_org/__init__.py"
        minimal_init.parent.mkdir(parents=True, exist_ok=True)
        minimal_init.write_text("\"\"\"Minimal preview dependency package.\"\"\"\n", encoding="utf-8")
        _write_cli(staging / CLI)
        (staging / "README.zh-CN.md").write_text(
            """# Factor Forge 知识模块预览\n\n这是离线、只读、advisory-only 的知识模块预览，不是完整 Ultimate 生产包，也不构成 canonical admission。正式因子研究仍通过已有 Factor Forge Ultimate 及其受治理数据环境执行。\n\n验收流程：先写下用户的原始经济/数学假设；再用 `query_knowledge.py` 获取历史案例的机制、失败条件、复用边界和来源；最后由研究者明确决定采用、拒绝或仅作类比。检索结果不代表收益、晋级或生产接纳。\n\n运行：`python3 query_knowledge.py --query '占用测度 价值 支撑'`；机器读取时加 `--json`。\n\n建议回放（均来自包内公开图谱真实节点）：\n\n- `占用测度 价值 支撑`：occupation measure / value-domain 案例。\n- `open volume correlation low turnover payer`：Alpha014 过滤器删除 payer 的失败边界。\n- `economic estimand mathematical model measurement`：机制先于算子的方法案例。\n- `MAD sparse event execution constraint`：MSZQ/MAD 失败或边界案例。\n- `小波分析`：数学方法参考节点；不是收益声称。\n- `tropical geometry 热带几何`：用于验证当前图谱未覆盖方法的 cold-start。\n\n打包副本会删除历史绩效数值（如 key_metrics/metric 类字段）及绝对个人路径，只保留经济机制、数学对象、失败条件、复用边界和相对来源。包内不含原 PDF、行情/OOS payload、Host keys/state、私人配置或完整 contracts。\n""",
            encoding="utf-8",
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    name = path.relative_to(staging).as_posix()
                    if name.startswith("/") or ".." in Path(name).parts:
                        raise ValueError(f"unsafe archive path: {name}")
                    archive.write(path, name)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a portable Factor Forge knowledge preview ZIP.")
    parser.add_argument("--source-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(build_preview(source_root=Path(args.source_root), output=Path(args.output)))


if __name__ == "__main__":
    main()
