#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLED_SKILL_ROOT = Path.home() / ".codex" / "skills"
KNOWLEDGE_ROOT = REPO_ROOT / "knowledge" / "因子工厂"
TAXONOMY_PATH = KNOWLEDGE_ROOT / "taxonomy" / "factor_taxonomy_v1.json"
MANIFEST_PATH = KNOWLEDGE_ROOT / "graph" / "factor_knowledge_graph_manifest.json"
NODES_DIR = KNOWLEDGE_ROOT / "graph" / "nodes"
COVERAGE_JSON_PATH = KNOWLEDGE_ROOT / "graph" / "factor_knowledge_coverage.json"
COVERAGE_MARKDOWN_PATH = KNOWLEDGE_ROOT / "仪表盘" / "知识网络覆盖率.md"
NETWORK_DASHBOARD_PATH = KNOWLEDGE_ROOT / "仪表盘" / "知识网络.md"

REQUIRED_TAXONOMY_CATEGORIES = {
    "market_consensus",
    "barra_style",
    "worldquant_style",
    "cn_quant_practice",
    "buyside_style",
    "economic_mechanism",
    "math_mechanism",
    "data_source",
    "tradability",
    "research_status",
    "failure_mode",
}

REQUIRED_BUYSIDE_TAGS = {
    "stat_arb_signal",
    "short_horizon_stat_arb",
    "medium_horizon_alpha",
    "pure_alpha_signal",
    "risk_premia_signal",
    "behavioral_alpha",
    "risk_factor",
    "microstructure_alpha",
    "flow_alpha",
    "liquidity_provider_signal",
    "execution_aware_alpha",
    "alpha_combination_feature",
    "ensemble_feature",
    "universe_selector",
    "alpha_decay_control",
    "regime_conditioner",
}

REQUIRED_MARKET_CONSENSUS_TAGS = {
    "momentum",
    "price_momentum",
    "earnings_momentum",
    "residual_momentum",
    "reversal",
    "short_term_reversal",
    "value",
    "quality",
    "low_volatility",
    "liquidity",
    "microstructure",
    "capital_flow",
    "crowding",
}

REQUIRED_CN_QUANT_TAGS = {
    "index_enhancement",
    "market_neutral",
    "intraday_reversal",
    "high_frequency_microstructure",
    "moneyflow_alpha",
    "small_mid_cap_alpha",
    "leader_following",
    "limit_up_down_microstructure",
    "feature_for_ml",
}

REQUIRED_ALIASES = {
    "动量类": "market_consensus:momentum",
    "反转类": "market_consensus:reversal",
    "资金流": "buyside_style:flow_alpha",
    "价量": "worldquant_style:price_volume",
    "私募资金流": "buyside_style:flow_alpha",
    "龙头战法": "cn_quant_practice:leader_following",
    "占用测度": "math_mechanism:occupation_measure",
}

INSTALLED_PARITY_FILES = [
    ("skills/factor-forge-researcher/SKILL.md", "factor-forge-researcher/SKILL.md"),
    ("skills/factor-forge-step1/SKILL.md", "factor-forge-step1/SKILL.md"),
    (
        "skills/factor-forge-step1/scripts/standardize_step1_research_fields.py",
        "factor-forge-step1/scripts/standardize_step1_research_fields.py",
    ),
    ("skills/factor-forge-step1/scripts/validate_step1.py", "factor-forge-step1/scripts/validate_step1.py"),
    ("skills/factor-forge-step2/SKILL.md", "factor-forge-step2/SKILL.md"),
    ("skills/factor-forge-step2/scripts/run_step2.py", "factor-forge-step2/scripts/run_step2.py"),
    ("skills/factor-forge-step2/scripts/validate_step2.py", "factor-forge-step2/scripts/validate_step2.py"),
    ("skills/factor-forge-step6/SKILL.md", "factor-forge-step6/SKILL.md"),
    ("skills/factor-forge-step6/scripts/run_step6.py", "factor-forge-step6/scripts/run_step6.py"),
]

GRAPH_ROOT = KNOWLEDGE_ROOT / "graph"
GRAPH_TEMPLATES_DIR = GRAPH_ROOT / "templates"
GRAPH_INDEX_FILES = [
    GRAPH_ROOT / "factor_knowledge_nodes.jsonl",
    GRAPH_ROOT / "factor_knowledge_edges.jsonl",
    GRAPH_ROOT / "factor_knowledge_graph_manifest.json",
    COVERAGE_JSON_PATH,
]
NETWORK_DASHBOARD_FILES = [
    NETWORK_DASHBOARD_PATH,
    COVERAGE_MARKDOWN_PATH,
]


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO_ROOT, check=True, text=True, capture_output=True)


def run_no_check(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO_ROOT, check=False, text=True, capture_output=True)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def check_taxonomy() -> dict[str, Any]:
    taxonomy = load_json(TAXONOMY_PATH)
    categories = taxonomy.get("categories") or {}
    aliases = taxonomy.get("aliases") or {}
    missing_categories = sorted(REQUIRED_TAXONOMY_CATEGORIES - set(categories))
    missing_buyside = sorted(REQUIRED_BUYSIDE_TAGS - set(categories.get("buyside_style") or []))
    missing_market_consensus = sorted(
        REQUIRED_MARKET_CONSENSUS_TAGS - set(categories.get("market_consensus") or [])
    )
    missing_cn_quant = sorted(REQUIRED_CN_QUANT_TAGS - set(categories.get("cn_quant_practice") or []))
    assert_true(not missing_categories, f"taxonomy missing categories: {missing_categories}")
    assert_true(not missing_buyside, f"taxonomy missing buyside tags: {missing_buyside}")
    assert_true(
        not missing_market_consensus,
        f"taxonomy missing market-consensus tags: {missing_market_consensus}",
    )
    assert_true(not missing_cn_quant, f"taxonomy missing CN quant tags: {missing_cn_quant}")
    missing_aliases: dict[str, str] = {}
    for alias, expected_tag in REQUIRED_ALIASES.items():
        if expected_tag not in set(aliases.get(alias) or []):
            missing_aliases[alias] = expected_tag
    assert_true(not missing_aliases, f"taxonomy missing aliases: {missing_aliases}")
    return {
        "category_count": len(categories),
        "market_consensus_tag_count": len(categories.get("market_consensus") or []),
        "cn_quant_tag_count": len(categories.get("cn_quant_practice") or []),
        "buyside_tag_count": len(categories.get("buyside_style") or []),
        "alias_count": len(aliases),
        "required_categories_present": True,
    }


def check_graph() -> dict[str, Any]:
    build = run([sys.executable, "scripts/build_factor_knowledge_graph.py"])
    manifest = json.loads(build.stdout)
    assert_true(manifest.get("node_count", 0) >= 4, "expected at least four knowledge graph nodes")
    assert_true(manifest.get("edge_count", 0) >= 18, "expected at least eighteen graph edges")
    tag_counts = manifest.get("tag_counts") or {}
    assert_true(tag_counts.get("buyside_style:microstructure_alpha", 0) >= 2, "missing buyside microstructure coverage")
    assert_true(tag_counts.get("buyside_style:flow_alpha", 0) >= 1, "missing buyside flow alpha coverage")
    return {
        "node_count": manifest.get("node_count"),
        "edge_count": manifest.get("edge_count"),
        "buyside_microstructure_count": tag_counts.get("buyside_style:microstructure_alpha", 0),
        "buyside_flow_alpha_count": tag_counts.get("buyside_style:flow_alpha", 0),
    }


def check_scoped_node_validator() -> dict[str, Any]:
    node_path = (
        NODES_DIR
        / "METHOD_MECHANISM_CONDITIONED_MEASUREMENT_SEARCH_20260807.json"
    )
    assert_true(node_path.exists(), f"missing scoped validator fixture node: {node_path}")
    proc = run([sys.executable, "scripts/validate_factor_knowledge_node.py", str(node_path)])
    payload = json.loads(proc.stdout)
    assert_true(payload.get("verdict") == "ACCEPT", "scoped node validator did not ACCEPT")
    assert_true(
        payload.get("node_id")
        == "node::method_mechanism_conditioned_measurement_search_20260807",
        f"scoped node validator checked unexpected node: {payload.get('node_id')}",
    )
    return {
        "validator": "scripts/validate_factor_knowledge_node.py",
        "fixture_node": repo_relative(node_path),
        "verdict": payload.get("verdict"),
    }


def check_alias_queries() -> dict[str, Any]:
    flow = run([sys.executable, "scripts/query_factor_knowledge_graph.py", "--tag", "资金流", "--top-k", "5"])
    flow_payload = json.loads(flow.stdout)
    flow_ids = {row.get("id") for row in flow_payload.get("results") or []}
    assert_true(
        "node::moneyflow_feature_candidates_v15_v18_v19_20260617" in flow_ids,
        f"alias query 资金流 did not retrieve moneyflow node: {sorted(flow_ids)}",
    )
    assert_true(
        flow_payload.get("alias_resolution", {}).get("资金流") == ["buyside_style:flow_alpha"],
        f"alias query 资金流 resolved unexpectedly: {flow_payload.get('alias_resolution')}",
    )

    occupation = run([sys.executable, "scripts/retrieve_factor_knowledge_context.py", "--tag", "占用测度", "--text", "CPV", "--top-k", "3"])
    occupation_payload = json.loads(occupation.stdout)
    occupation_ids = {node.get("id") for node in occupation_payload.get("nodes") or []}
    assert_true(
        "node::cpv_occ_loc_stability_v3_20260616" in occupation_ids,
        f"alias context 占用测度 did not retrieve CPV node: {sorted(occupation_ids)}",
    )
    assert_true(
        occupation_payload.get("query", {}).get("alias_resolution", {}).get("占用测度") == [
            "math_mechanism:occupation_measure"
        ],
        f"alias context 占用测度 resolved unexpectedly: {occupation_payload.get('query', {}).get('alias_resolution')}",
    )
    return {
        "query_alias_smoke": "资金流",
        "context_alias_smoke": "占用测度",
        "verdict": "ACCEPT",
    }


def check_writeback_assets() -> dict[str, Any]:
    template_path = GRAPH_TEMPLATES_DIR / "factor_knowledge_node_template.json"
    guide_path = GRAPH_TEMPLATES_DIR / "factor_knowledge_node_writeback_guide.md"
    assert_true(template_path.exists(), f"missing node template: {template_path}")
    assert_true(guide_path.exists(), f"missing node writeback guide: {guide_path}")

    template = load_json(template_path)
    template_taxonomy = template.get("taxonomy") or {}
    template_required_tags = {
        "market_consensus": {"momentum", "reversal", "microstructure", "capital_flow"},
        "worldquant_style": {"price_volume", "rank_transform", "ts_operator"},
        "cn_quant_practice": {"index_enhancement", "market_neutral", "moneyflow_alpha", "feature_for_ml"},
        "buyside_style": {"stat_arb_signal", "microstructure_alpha", "flow_alpha", "alpha_combination_feature"},
    }
    missing_template_tags: dict[str, list[str]] = {}
    for category, required_tags in template_required_tags.items():
        actual = set(template_taxonomy.get(category) or [])
        missing = sorted(required_tags - actual)
        if missing:
            missing_template_tags[category] = missing
    assert_true(not missing_template_tags, f"template missing taxonomy example tags: {missing_template_tags}")

    guide_text = guide_path.read_text(encoding="utf-8")
    guide_required_terms = [
        "price_momentum",
        "earnings_momentum",
        "short_term_reversal",
        "capital_flow",
        "moneyflow_alpha",
        "leader_following",
        "flow_alpha",
        "execution_aware_alpha",
        "ensemble_feature",
    ]
    missing_guide_terms = [term for term in guide_required_terms if term not in guide_text]
    assert_true(not missing_guide_terms, f"writeback guide missing taxonomy terms: {missing_guide_terms}")
    return {
        "template_path": repo_relative(template_path),
        "guide_path": repo_relative(guide_path),
        "template_taxonomy_examples_present": True,
        "guide_taxonomy_examples_present": True,
    }


def has_any_key(mapping: dict[str, Any], keys: set[str]) -> bool:
    return any(key in mapping and mapping.get(key) not in (None, "", [], {}) for key in keys)


def repo_relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def is_remote_path(value: str) -> bool:
    return "://" in value


def validate_source_path(node_id: str, source_path: str) -> str:
    if source_path.startswith("/tmp/"):
        raise SystemExit(f"{node_id}: source_paths must not point to temporary files: {source_path}")
    if is_remote_path(source_path):
        return "remote"
    path = Path(source_path)
    if path.is_absolute():
        try:
            repo_rel = path.resolve().relative_to(REPO_ROOT)
        except ValueError:
            return "external_local"
        candidate = REPO_ROOT / repo_rel
    else:
        candidate = REPO_ROOT / source_path
    if candidate.exists():
        return "repo_local"
    normalized = Path(source_path).as_posix()
    if normalized.startswith("factor_research/"):
        return "workspace_provenance_unavailable"
    raise SystemExit(f"{node_id}: source_path does not exist: {source_path}")


def check_node_quality() -> dict[str, Any]:
    required_taxonomy = {
        "market_consensus",
        "economic_mechanism",
        "math_mechanism",
        "data_source",
        "tradability",
        "research_status",
    }
    equation_keys = {
        "key_equation_latex",
        "formula_latex",
        "state_equation_latex",
        "payoff_equation_latex",
        "occupation_measure_latex",
        "signal_latex",
        "formula_candidates",
        "factor_expression",
    }
    insight_keys = {
        "dirac_style_forced_insight",
        "math_forced_insight",
        "information_preserved_removed",
        "complexity_penalty_reasoning",
    }
    evidence_window_keys = {"window", "source_window", "is_window", "sample_window", "oos_window"}
    evidence_boundary_keys = {"falsification", "boundary", "verdict", "classification"}
    useful_relation_edges = {"uses_math", "shares_failure_with", "contradicts", "reusable_as", "refines", "inspires"}

    checked_nodes: list[str] = []
    checked_source_paths = 0
    external_source_paths = 0
    for path in sorted(NODES_DIR.glob("*.json")):
        node = load_json(path)
        node_id = str(node.get("id") or path.name)
        taxonomy = node.get("taxonomy") or {}
        missing_taxonomy = sorted(category for category in required_taxonomy if not taxonomy.get(category))
        assert_true(not missing_taxonomy, f"{node_id}: missing required taxonomy values {missing_taxonomy}")

        mechanism = node.get("mechanism") or {}
        evidence = node.get("evidence") or {}
        relations = node.get("relations") or []
        relation_edge_types = {relation.get("edge_type") for relation in relations if isinstance(relation, dict)}

        node_type = str(node.get("node_type") or "")
        if node_type == "methodology":
            for field in (
                "authority_chain",
                "knowledge_boundary",
                "applicability_boundary",
                "failure_localization",
            ):
                assert_true(bool(mechanism.get(field)), f"{node_id}: missing methodology.{field}")
            assert_true(bool(evidence.get("contract_version")), f"{node_id}: missing methodology contract_version")
        else:
            assert_true(bool(mechanism.get("payer") or mechanism.get("economic_hypothesis")), f"{node_id}: missing payer/economic hypothesis")
            assert_true(bool(mechanism.get("receiver") or node_type == "data_state"), f"{node_id}: missing receiver")
            assert_true(
                bool(mechanism.get("mathematical_object") or mechanism.get("random_object")),
                f"{node_id}: missing mathematical_object",
            )
            assert_true(has_any_key(mechanism, equation_keys), f"{node_id}: missing equation/formula/law reference")
            assert_true(has_any_key(mechanism, insight_keys), f"{node_id}: missing Dirac/math-forced insight or transform note")
            assert_true(has_any_key(evidence, evidence_window_keys), f"{node_id}: missing evidence window")
            assert_true(bool(evidence.get("key_metrics")), f"{node_id}: missing key_metrics")
        assert_true(has_any_key(evidence, evidence_boundary_keys), f"{node_id}: missing falsification/boundary/verdict")
        source_paths = node.get("source_paths") or []
        assert_true(bool(source_paths), f"{node_id}: missing source_paths")
        for source_path in source_paths:
            assert_true(isinstance(source_path, str) and source_path, f"{node_id}: invalid source_path {source_path!r}")
            source_path_kind = validate_source_path(node_id, source_path)
            if source_path_kind == "repo_local":
                checked_source_paths += 1
            else:
                external_source_paths += 1
        assert_true(bool(node.get("reuse_guidance")), f"{node_id}: missing reuse_guidance")
        assert_true(bool(useful_relation_edges & relation_edge_types), f"{node_id}: missing useful relation edge")
        checked_nodes.append(node_id)

    assert_true(bool(checked_nodes), "no graph nodes checked")
    return {
        "checked_count": len(checked_nodes),
        "checked_nodes": checked_nodes,
        "checked_repo_source_paths": checked_source_paths,
        "external_source_paths": external_source_paths,
    }


def check_smokes() -> dict[str, Any]:
    smoke = run([sys.executable, "scripts/run_factor_knowledge_graph_smoke.py"])
    payload = json.loads(smoke.stdout)
    assert_true(payload.get("verdict") == "ACCEPT", "graph smoke did not ACCEPT")
    for key in [
        "step1_context_integration_found",
        "step2_context_integration_found",
        "step6_context_integration_found",
        "buyside_microstructure_nodes_found",
    ]:
        assert_true(payload.get(key) is True, f"graph smoke missing {key}")
    return payload


def check_commit_scope_validator() -> dict[str, Any]:
    proc = run([sys.executable, "scripts/validate_factor_knowledge_commit_scope.py"])
    payload = json.loads(proc.stdout)
    assert_true(payload.get("verdict") == "ACCEPT", "commit scope validator did not ACCEPT")
    assert_true(
        "scripts/validate_factor_knowledge_commit_scope.py" in set(payload.get("allowed_paths") or []),
        "commit scope validator is not in its own allowlist",
    )
    assert_true(bool(payload.get("force_add_paths")), "commit scope validator missing force-add paths")

    positive = run([
        sys.executable,
        "scripts/validate_factor_knowledge_commit_scope.py",
        "--paths",
        "scripts/validate_factor_knowledge_commit_scope.py",
    ])
    positive_payload = json.loads(positive.stdout)
    assert_true(positive_payload.get("verdict") == "ACCEPT", "commit scope positive path did not ACCEPT")

    negative = run_no_check([
        sys.executable,
        "scripts/validate_factor_knowledge_commit_scope.py",
        "--paths",
        "factor_research/example_bad_scope/result.json",
    ])
    assert_true(negative.returncode != 0, "commit scope negative path unexpectedly returned success")
    negative_payload = json.loads(negative.stdout)
    assert_true(
        negative_payload.get("verdict") == "BLOCK",
        f"commit scope negative path did not BLOCK: {negative_payload}",
    )
    assert_true(
        negative_payload.get("unexpected_staged_paths") == ["factor_research/example_bad_scope/result.json"],
        f"commit scope negative path blocked wrong paths: {negative_payload.get('unexpected_staged_paths')}",
    )
    return {
        "validator": "scripts/validate_factor_knowledge_commit_scope.py",
        "verdict": payload.get("verdict"),
        "allowed_count": payload.get("allowed_count"),
        "force_add_count": len(payload.get("force_add_paths") or []),
        "positive_path_smoke": positive_payload.get("verdict"),
        "negative_path_smoke": negative_payload.get("verdict"),
    }


def check_coverage_report() -> dict[str, Any]:
    coverage = run(
        [
            sys.executable,
            "scripts/report_factor_knowledge_graph_coverage.py",
            "--json-output",
            str(COVERAGE_JSON_PATH),
            "--markdown-output",
            str(COVERAGE_MARKDOWN_PATH),
        ]
    )
    payload = json.loads(coverage.stdout)
    assert_true(payload.get("graph_node_count", 0) >= 4, "coverage report sees too few graph nodes")
    assert_true((payload.get("library_coverage") or {}).get("ordinary_factor_library"), "coverage report missing ordinary library")
    assert_true("missing_high_priority_count" in payload, "coverage report missing high-priority backlog count")
    return payload


def check_dashboard_sync() -> dict[str, Any]:
    assert_true(NETWORK_DASHBOARD_PATH.exists(), f"missing network dashboard: {NETWORK_DASHBOARD_PATH}")
    dashboard_text = NETWORK_DASHBOARD_PATH.read_text(encoding="utf-8")
    manifest = load_json(MANIFEST_PATH)
    node_ids: list[str] = []
    for row in (MANIFEST_PATH.parent / "factor_knowledge_nodes.jsonl").read_text(encoding="utf-8").splitlines():
        if not row.strip():
            continue
        node_id = json.loads(row).get("id")
        if node_id:
            node_ids.append(str(node_id))
    missing_node_ids = sorted(node_id for node_id in node_ids if node_id not in dashboard_text)
    assert_true(not missing_node_ids, f"network dashboard missing graph nodes: {missing_node_ids}")
    for required_text in [
        "market_consensus:momentum",
        "market_consensus:price_momentum",
        "market_consensus:earnings_momentum",
        "market_consensus:residual_momentum",
        "market_consensus:reversal",
        "market_consensus:short_term_reversal",
        "market_consensus:value",
        "market_consensus:quality",
        "market_consensus:capital_flow",
        "market_consensus:crowding",
        "buyside_style:stat_arb_signal",
        "buyside_style:short_horizon_stat_arb",
        "buyside_style:medium_horizon_alpha",
        "buyside_style:pure_alpha_signal",
        "buyside_style:risk_premia_signal",
        "buyside_style:flow_alpha",
        "buyside_style:ensemble_feature",
        "buyside_style:universe_selector",
        "math_mechanism:first_passage",
        "failure_mode:turnover_cost_exceeds_gross_edge",
    ]:
        assert_true(required_text in dashboard_text, f"network dashboard missing query entry: {required_text}")
    return {
        "dashboard_path": str(NETWORK_DASHBOARD_PATH),
        "node_count": manifest.get("node_count"),
        "all_node_ids_listed": True,
    }


def check_installed_parity() -> dict[str, Any]:
    checked: list[str] = []
    for repo_rel, installed_rel in INSTALLED_PARITY_FILES:
        repo_path = REPO_ROOT / repo_rel
        installed_path = INSTALLED_SKILL_ROOT / installed_rel
        assert_true(repo_path.exists(), f"missing repo file: {repo_path}")
        assert_true(installed_path.exists(), f"missing installed file: {installed_path}")
        if repo_path.read_bytes() != installed_path.read_bytes():
            raise SystemExit(f"installed skill differs from repo: {repo_rel} != {installed_path}")
        checked.append(repo_rel)
    return {"checked_count": len(checked), "checked_files": checked}


def check_force_add_paths() -> dict[str, Any]:
    force_add_paths = sorted(
        {
            repo_relative(TAXONOMY_PATH),
            *[repo_relative(path) for path in sorted(NODES_DIR.glob("*.json"))],
            *[repo_relative(path) for path in sorted(GRAPH_TEMPLATES_DIR.glob("*")) if path.is_file()],
            *[repo_relative(path) for path in GRAPH_INDEX_FILES],
            *[repo_relative(path) for path in NETWORK_DASHBOARD_FILES],
        }
    )
    missing = [path for path in force_add_paths if not (REPO_ROOT / path).exists()]
    assert_true(not missing, f"knowledge files missing: {missing}")
    return {
        "force_add_required": True,
        "reason": "knowledge/因子工厂 is ignored locally; use git add -f for these graph/taxonomy/dashboard files",
        "path_count": len(force_add_paths),
        "paths": force_add_paths,
    }


def main() -> None:
    result = {
        "verdict": "ACCEPT",
        "taxonomy": check_taxonomy(),
        "writeback_assets": check_writeback_assets(),
        "scoped_node_validator": check_scoped_node_validator(),
        "alias_queries": check_alias_queries(),
        "graph": check_graph(),
        "node_quality": check_node_quality(),
        "smoke": check_smokes(),
        "commit_scope_validator": check_commit_scope_validator(),
        "coverage": check_coverage_report(),
        "dashboard": check_dashboard_sync(),
        "installed_parity": check_installed_parity(),
        "version_control": check_force_add_paths(),
        "manifest_path": str(MANIFEST_PATH),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
