from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_knowledge_readiness_module():
    path = PROJECT_ROOT / "scripts" / "run_factor_knowledge_network_readiness.py"
    spec = importlib.util.spec_from_file_location("factorforge_knowledge_readiness_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_knowledge_index_references_only_tracked_checkout_nodes() -> None:
    index_path = PROJECT_ROOT / "knowledge/因子工厂/graph/factor_knowledge_nodes.jsonl"
    failures: list[str] = []
    for raw in index_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(raw)
        source = Path(str(row.get("source_node_path") or ""))
        try:
            marker_index = source.parts.index("knowledge")
        except ValueError:
            failures.append(f"{row.get('id')}: source path is outside knowledge")
            continue
        relative = Path(*source.parts[marker_index:])
        if not (PROJECT_ROOT / relative).is_file():
            failures.append(f"{row.get('id')}: source file missing: {relative}")
            continue
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(relative)],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if tracked.returncode != 0:
            failures.append(f"{row.get('id')}: source file untracked: {relative}")

    assert failures == []


def test_missing_current_knowledge_source_blocks_but_historical_workspace_can_be_unavailable(
    tmp_path, monkeypatch
) -> None:
    module = _load_knowledge_readiness_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    with pytest.raises(SystemExit, match="source_path does not exist"):
        module.validate_source_path(
            "node::current_missing",
            "knowledge/因子工厂/graph/nodes/definitely_missing.json",
        )

    assert module.validate_source_path(
        "node::historical_workspace",
        "factor_research/retired_factor/objects/evidence.json",
    ) == "workspace_provenance_unavailable"


def test_knowledge_quality_accepts_dcf_mathematical_object_without_random_object(
    tmp_path, monkeypatch
) -> None:
    module = _load_knowledge_readiness_module()
    nodes_dir = tmp_path / "knowledge" / "因子工厂" / "graph" / "nodes"
    nodes_dir.mkdir(parents=True)
    evidence_path = tmp_path / "docs" / "dcf_evidence.md"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text("DCF evidence\n", encoding="utf-8")
    node = {
        "id": "node::dcf_mechanism",
        "node_type": "factor_case",
        "taxonomy": {
            "market_consensus": ["value"],
            "economic_mechanism": ["information_processing"],
            "math_mechanism": ["discounted_cash_flow"],
            "data_source": ["fundamentals"],
            "tradability": ["long_side"],
            "research_status": ["candidate"],
        },
        "mechanism": {
            "payer": "stale valuation anchors",
            "receiver": "valuation-aware capital",
            "mathematical_object": "present value of legal-time forecast cash flows",
            "key_equation_latex": "V=FCF/(WACC-g)",
            "math_forced_insight": "discount spread must stay positive",
        },
        "evidence": {
            "window": "synthetic contract fixture",
            "key_metrics": {"rank_ic": 0.01},
            "verdict": "candidate",
        },
        "relations": [{"edge_type": "uses_math", "target": "method::dcf"}],
        "reuse_guidance": ["Use legal publication time."],
        "source_paths": [str(evidence_path)],
    }
    (nodes_dir / "DCF.json").write_text(
        json.dumps(node, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "NODES_DIR", nodes_dir)

    result = module.check_node_quality()

    assert result["checked_nodes"] == ["node::dcf_mechanism"]


def test_knowledge_graph_node_path_remaps_cross_host_absolute_path(tmp_path, monkeypatch):
    import factor_factory.knowledge_context as knowledge

    monkeypatch.setattr(knowledge, "REPO_ROOT", tmp_path)
    node_path = tmp_path / "knowledge" / "因子工厂" / "graph" / "nodes" / "opening_case.json"
    node_path.parent.mkdir(parents=True)
    node_path.write_text(
        json.dumps(
            {
                "id": "node::opening_case",
                "node_type": "factor_case",
                "title": "Opening pressure case",
                "summary": "Opening pressure must be separated from reversal and liquidity aliases.",
                "taxonomy": {"research_status": ["rejected"]},
                "reuse_guidance": ["Preserve the alias controls."],
            }
        ),
        encoding="utf-8",
    )
    stale_path = "/Users/old-host/project/knowledge/因子工厂/graph/nodes/opening_case.json"
    node_index = tmp_path / "node_index.jsonl"
    node_index.write_text(
        json.dumps(
            {
                "id": "node::opening_case",
                "title": "Opening pressure case",
                "summary": "Opening pressure reversal liquidity",
                "tags": ["opening"],
                "research_status": ["rejected"],
                "source_node_path": stale_path,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    edge_index = tmp_path / "edge_index.jsonl"
    edge_index.write_text("", encoding="utf-8")

    context = knowledge.retrieve_factor_knowledge_context(
        text="opening pressure reversal",
        top_k=3,
        node_index=node_index,
        edge_index=edge_index,
        taxonomy=tmp_path / "missing_taxonomy.json",
    )

    assert context["node_count"] == 1
    assert context["nodes"][0]["id"] == "node::opening_case"
    assert context["nodes"][0]["reuse_guidance"] == ["Preserve the alias controls."]


def test_current_checkout_node_wins_over_existing_stale_checkout(tmp_path, monkeypatch):
    import factor_factory.knowledge_context as module

    current_root = tmp_path / "current"
    stale_root = tmp_path / "stale"
    relative = Path("knowledge/因子工厂/graph/nodes/case.json")
    current_path = current_root / relative
    stale_path = stale_root / relative
    current_path.parent.mkdir(parents=True)
    stale_path.parent.mkdir(parents=True)
    current_path.write_text('{"id":"current"}\n', encoding="utf-8")
    stale_path.write_text('{"id":"stale"}\n', encoding="utf-8")
    monkeypatch.setattr(module, "REPO_ROOT", current_root)

    assert module.resolve_graph_node_path(stale_path) == current_path


def test_stale_checkout_node_is_not_used_when_current_node_is_missing(tmp_path, monkeypatch):
    import factor_factory.knowledge_context as module

    current_root = tmp_path / "current"
    stale_path = tmp_path / "stale" / "knowledge/因子工厂/graph/nodes/case.json"
    stale_path.parent.mkdir(parents=True)
    stale_path.write_text('{"id":"stale"}\n', encoding="utf-8")
    monkeypatch.setattr(module, "REPO_ROOT", current_root)

    resolved = module.resolve_graph_node_path(stale_path)

    assert resolved == current_root / "knowledge/因子工厂/graph/nodes/case.json"
    assert not resolved.exists()


def test_retrieval_blocks_when_any_indexed_node_path_is_stale(tmp_path, monkeypatch):
    import factor_factory.knowledge_context as module

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    node_index = tmp_path / "factor_knowledge_nodes.jsonl"
    edge_index = tmp_path / "factor_knowledge_edges.jsonl"
    node_index.write_text(
        json.dumps(
            {
                "id": "node::stale",
                "title": "Stale knowledge row",
                "summary": "This row must never become a false cold start.",
                "source_node_path": str(
                    tmp_path
                    / "knowledge"
                    / "因子工厂"
                    / "graph"
                    / "nodes"
                    / "missing.json"
                ),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    edge_index.write_text("", encoding="utf-8")

    with pytest.raises(
        module.KnowledgeRetrievalError,
        match=module.BLOCK_KNOWLEDGE_RETRIEVAL_UNAVAILABLE,
    ):
        module.retrieve_factor_knowledge_context(
            text="unrelated query",
            node_index=node_index,
            edge_index=edge_index,
            taxonomy=tmp_path / "missing_taxonomy.json",
        )


def test_missing_indexes_block_without_creating_or_building_files(tmp_path) -> None:
    import factor_factory.knowledge_context as module

    graph_root = tmp_path / "missing_graph"
    node_index = graph_root / "factor_knowledge_nodes.jsonl"
    edge_index = graph_root / "factor_knowledge_edges.jsonl"

    with pytest.raises(
        module.KnowledgeRetrievalError,
        match=module.BLOCK_KNOWLEDGE_RETRIEVAL_UNAVAILABLE,
    ):
        module.retrieve_factor_knowledge_context(
            text="liquidity pressure",
            node_index=node_index,
            edge_index=edge_index,
            taxonomy=graph_root / "taxonomy.json",
        )

    assert not graph_root.exists()


@pytest.mark.parametrize("compatibility_flag", [False, True])
def test_retrieval_cli_is_read_only_when_indexes_are_missing(
    tmp_path: Path,
    compatibility_flag: bool,
) -> None:
    graph_root = tmp_path / "missing_cli_graph"
    command = [
        "python3",
        "scripts/retrieve_factor_knowledge_context.py",
        "--node-index",
        str(graph_root / "nodes.jsonl"),
        "--edge-index",
        str(graph_root / "edges.jsonl"),
        "--taxonomy",
        str(graph_root / "taxonomy.json"),
        "--text",
        "liquidity pressure",
    ]
    if compatibility_flag:
        command.append("--no-build")
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "BLOCK_FACTORFORGE_KNOWLEDGE_RETRIEVAL_UNAVAILABLE" in completed.stderr
    assert not graph_root.exists()


def test_retrieval_cli_has_no_output_file_write_surface(tmp_path: Path) -> None:
    protected_index = tmp_path / "protected-index.jsonl"
    original = b'{"sentinel":true}\n'
    protected_index.write_bytes(original)

    completed = subprocess.run(
        [
            "python3",
            "scripts/retrieve_factor_knowledge_context.py",
            "--output",
            str(protected_index),
            "--text",
            "liquidity pressure",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "unrecognized arguments: --output" in completed.stderr
    assert protected_index.read_bytes() == original


def test_researcher_skill_forbids_direct_repo_graph_writeback() -> None:
    skill = (PROJECT_ROOT / "skills/factor-forge-researcher/SKILL.md").read_text(
        encoding="utf-8"
    )
    retrieval_cli = (
        PROJECT_ROOT / "scripts/retrieve_factor_knowledge_context.py"
    ).read_text(encoding="utf-8")

    assert "write a machine-readable knowledge node under" not in skill
    assert "build_factor_knowledge_graph.py" not in retrieval_cli
    assert "subprocess.run" not in retrieval_cli


def test_formula_semantics_retrieve_prior_distribution_regime_case() -> None:
    import factor_factory.knowledge_context as module

    context = module.retrieve_factor_knowledge_context(
        text=(
            "NORMALIZE S_LOG_LP TS_KURTOSIS CLOSE TS_MAX_SKEW VOLUME "
            "TS_MIN_SKEW TS_MAX_SUM CHANGE_PCT"
        ),
        top_k=5,
    )

    assert "node::alpha007_regime_kurt_skew_20260422" in {
        node["id"] for node in context["nodes"]
    }
