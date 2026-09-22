from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_chinese_query_tokenization_and_math_family_expansion() -> None:
    import factor_factory.knowledge_context as knowledge

    tokens = knowledge.tokenize("多尺度局部能量与流动性撤退")
    assert {"多尺度", "局部", "能量", "流动性", "撤退"} <= tokens

    expanded = knowledge.semantic_query_terms("小波 卡尔曼 卷积 变分")
    assert {
        "multiscale",
        "time_frequency",
        "state_space",
        "filtering",
        "kernel",
        "latent_state",
        "regularization",
    } <= expanded

    specific = knowledge.semantic_query_specific_terms("小波")
    bridge = knowledge.semantic_query_bridge_terms("小波")
    assert "wavelet" in specific
    assert "multiscale" not in specific
    assert "multiscale" in bridge
    assert "wavelet" not in bridge


def test_tokenize_nfkc_greek_and_math_symbols_deterministically() -> None:
    import factor_factory.knowledge_context as knowledge

    tokens = knowledge.tokenize("ＬＩＱＵＩＤＩＴＹ Δρ σ μ λ ∑ ∫ ∇ ⊗")

    assert {
        "liquidity",
        "δ",
        "delta",
        "ρ",
        "rho",
        "σ",
        "sigma",
        "μ",
        "mu",
        "λ",
        "lambda",
        "∑",
        "sum",
        "∫",
        "integral",
        "∇",
        "nabla",
        "⊗",
        "tensor_product",
    } <= tokens


@pytest.mark.parametrize(
    ("query", "longer_token"),
    [("energy", "synergy"), ("liquidity", "illiquidity")],
)
def test_generic_query_does_not_match_longer_suffix_token(
    query: str, longer_token: str
) -> None:
    import factor_factory.knowledge_context as knowledge

    score, overlap = knowledge.score_text(
        query,
        {"title": longer_token, "text": longer_token, "tags": [longer_token]},
    )

    assert score == 0.0
    assert overlap == []


def test_exact_liquidity_anchor_is_bilingual_but_bridge_suffix_is_not_anchor() -> None:
    import factor_factory.knowledge_context as knowledge

    english_score, _ = knowledge.score_text(
        "流动性",
        {"title": "liquidity", "text": "", "tags": ["liquidity"]},
    )
    chinese_score, _ = knowledge.score_text(
        "liquidity",
        {"title": "流动性", "text": "", "tags": ["流动性"]},
    )
    suffix_score, suffix_overlap = knowledge.score_text(
        "liquidity",
        {
            "title": "provision bridge",
            "text": "liquidity_provision",
            "tags": ["economic_mechanism:liquidity_provision"],
        },
    )

    assert english_score > 0.0
    assert chinese_score > 0.0
    assert suffix_score == 0.0
    assert suffix_overlap == []


@pytest.mark.parametrize(
    ("query", "bridge_text", "dedicated_tag"),
    [
        ("小波分析", "multiscale time_frequency local_energy", "math_mechanism:wavelet_transform"),
        ("卷积", "kernel local_filter multiscale", "math_mechanism:convolution"),
    ],
)
def test_named_math_requires_dedicated_anchor_not_bridge_overlap(
    query: str,
    bridge_text: str,
    dedicated_tag: str,
) -> None:
    import factor_factory.knowledge_context as knowledge

    bridge_only_score, bridge_only_overlap = knowledge.score_text(
        query,
        {
            "title": "generic mathematical bridge",
            "text": bridge_text,
            "tags": ["math_mechanism:path_functional"],
        },
    )
    anchored_score, anchored_overlap = knowledge.score_text(
        query,
        {
            "title": "dedicated mathematical method",
            "text": bridge_text,
            "tags": [dedicated_tag],
        },
    )

    assert bridge_only_score == 0.0
    assert bridge_only_overlap == []
    assert anchored_score > 0.0
    assert anchored_overlap


def test_missing_named_math_can_return_only_via_independent_mechanism_bridges() -> None:
    import factor_factory.knowledge_context as knowledge

    score, overlap = knowledge.score_text(
        "小波分析用于拥挤持有者和流动性撤退下的价格压力",
        {
            "title": "constraint driven liquidity pressure",
            "text": (
                "crowded holders face liquidity_provision withdrawal constraint "
                "and inventory_pressure"
            ),
            "tags": ["economic_mechanism:forced_flow"],
        },
    )

    assert score > 0.0
    assert "wavelet" not in overlap
    assert {"constraint", "liquidity_provision"} <= set(overlap)

    math_only_score, math_only_overlap = knowledge.score_text(
        "小波局部能量尺度分析",
        {
            "title": "generic multiscale context",
            "text": "multiscale local localized energy local_energy time_frequency",
            "tags": ["math_mechanism:path_functional"],
        },
    )
    assert math_only_score == 0.0
    assert math_only_overlap == []


@pytest.mark.parametrize(
    ("query", "generic_text"),
    [
        ("小波分析", "general 分析 framework"),
        ("卷积模型", "ordinary 模型 framework"),
        ("卡尔曼滤波", "general 滤波 estimator"),
    ],
)
def test_named_math_generic_companion_cannot_create_lexical_fallback(
    query: str, generic_text: str
) -> None:
    import factor_factory.knowledge_context as knowledge

    score, overlap = knowledge.score_text(
        query,
        {
            "title": "generic research object",
            "text": generic_text,
            "tags": ["generic_method"],
        },
    )

    assert score == 0.0
    assert overlap == []


def test_wavelet_formula_alias_requires_typed_anchor_and_ignores_plain_symbols() -> None:
    import factor_factory.knowledge_context as knowledge

    typed_score, typed_overlap = knowledge.score_text(
        "ψ + ∫",
        {
            "title": "typed wavelet precedent",
            "text": "multiscale localization",
            "tags": ["math_mechanism:wavelet_transform"],
        },
    )
    generic_score, generic_overlap = knowledge.score_text(
        "ψ + ∫",
        {
            "title": "ordinary integral model",
            "text": "psi integral analysis framework",
            "tags": ["math_mechanism:path_functional"],
        },
    )

    assert typed_score > 0.0
    assert "wavelet_transform" in typed_overlap
    assert generic_score == 0.0
    assert generic_overlap == []


def test_one_generic_bridge_concept_is_not_hit_but_two_independent_concepts_are() -> None:
    import factor_factory.knowledge_context as knowledge

    energy_only_score, _ = knowledge.score_text(
        "能量",
        {"text": "energy local_energy multiscale", "tags": ["local_energy"]},
    )
    two_concept_score, overlap = knowledge.score_text(
        "能量与尺度",
        {"text": "energy local_energy multiscale", "tags": ["local_energy"]},
    )

    assert energy_only_score == 0.0
    assert two_concept_score > 0.0
    assert {"energy", "multiscale"} <= set(overlap)


def test_natural_chinese_mechanism_query_ranks_relevant_bridge_above_generic_math() -> None:
    import factor_factory.knowledge_context as knowledge

    query = "拥挤交易导致流动性撤退与价格压力"
    relevant_score, relevant_overlap = knowledge.score_text(
        query,
        {
            "title": "liquidity pressure mechanism",
            "text": "crowded liquidity_provision constraint price pressure",
            "tags": ["economic_mechanism:liquidity_provision"],
        },
    )
    generic_score, _ = knowledge.score_text(
        query,
        {
            "title": "generic mathematical context",
            "text": "multiscale local energy path functional",
            "tags": ["math_mechanism:path_functional"],
        },
    )

    assert relevant_score > generic_score
    assert relevant_score > 0.0
    assert {"liquidity_provision", "constraint"} <= set(relevant_overlap)


def test_real_knowledge_graph_accepts_natural_chinese_mechanism_query() -> None:
    import factor_factory.knowledge_context as knowledge

    context = knowledge.retrieve_factor_knowledge_context(
        text="多尺度局部化时频能量、拥挤与流动性撤退",
        top_k=5,
    )

    assert context["node_count"] > 0
    assert context["nodes"][0]["id"] in {
        "node::alpha015_corr_rank_volume_pressure_20260618",
        "node::cpv_occ_loc_stability_v3_20260616",
    }
    assert any(
        {"liquidity", "path_functional"} & set(node["overlap_terms"])
        for node in context["nodes"]
    )


@pytest.mark.parametrize("query", ["小波分析", "卷积", "能量"])
def test_generic_math_or_bridge_term_alone_is_truthful_zero_hit(query: str, tmp_path) -> None:
    import factor_factory.knowledge_context as knowledge
    # Freeze the older, anchor-absent corpus as a fixture. Adding a genuine
    # method reference must not weaken the no-false-analogy behavior.
    excluded = "node::method_transient_signal_models_20260907"
    nodes = tmp_path / "nodes.jsonl"
    edges = tmp_path / "edges.jsonl"
    for original, target, field in (
        (knowledge.DEFAULT_NODE_INDEX, nodes, "id"),
        (knowledge.DEFAULT_EDGE_INDEX, edges, "source"),
    ):
        rows = [json.loads(line) for line in original.read_text().splitlines() if line.strip()]
        target.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows if row[field] != excluded))
    context = knowledge.retrieve_factor_knowledge_context(
        text=query, top_k=10, node_index=nodes, edge_index=edges,
        graph_root=knowledge.DEFAULT_GRAPH_ROOT,
    )

    assert context["node_count"] == 0
    assert context["nodes"] == []


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
