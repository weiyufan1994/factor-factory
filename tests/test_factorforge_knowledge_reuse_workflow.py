"""Knowledge-only acceptance: public historical cases and synthetic writeback.

No factor study, return calculation, OOS read, or canonical memory admission.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import factor_factory.knowledge_reference as knowledge_reference
from factor_factory.knowledge_context import (
    KnowledgeRetrievalError,
    resolve_graph_node_path,
    retrieve_factor_knowledge_context,
)
from factor_factory.knowledge_reference import (
    build_knowledge_reference_contract,
    validate_knowledge_reference_contract,
)


REPO = Path(__file__).resolve().parents[1]
VAULT = REPO / "knowledge/因子工厂"
_OPTIONAL_EVENT_U_SEED = (
    VAULT / "workspace_experience_exports"
    / "knowledge_record__RPT_web_8596d811_20250508_mszq_intraday_momentum_pulse__correction_20260908.json"
)
_EVENT_U_SEED_IDENTITY = {
    "report_id": "RPT_web_8596d811_20250508_mszq_intraday_momentum_pulse",
    "factor_id": "mszq_intraday_momentum_pulse",
    "research_variant": "EVENT_U_SOURCE_EXTENSION",
}
_PFVV_SEED_IDENTITY = {
    "report_id": "RPT_pdf_11d72_pfvv_20250508_mszq",
    "factor_id": "mszq_pfvv_source_baseline",
}


def _pfvv_candidate_seed_or_skip() -> dict:
    """Return the real PF/VV export; skip only before that export is packaged."""

    exports = VAULT / "workspace_experience_exports"
    matches = []
    suspicious = []
    for path in sorted(exports.glob("knowledge_record__*.json")):
        name = path.name.casefold()
        if "pfvv" in name or "11d72" in name:
            suspicious.append(path)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            if path in suspicious:
                pytest.fail(f"PFVV candidate seed is malformed: {path}")
            continue
        if all(record.get(key) == value for key, value in _PFVV_SEED_IDENTITY.items()):
            matches.append((path, record))
    if not matches:
        if suspicious:
            pytest.fail(
                "PFVV-named export exists but does not carry the required "
                "PFVV source-baseline identity"
            )
        pytest.skip(
            "real PFVV candidate seed is not packaged in workspace_experience_exports"
        )
    assert len(matches) == 1, "PFVV candidate seed must have one active identity"
    path, record = matches[0]
    assert record.get("export_status") == "LOCAL_PROJECT_ADVISORY_CANDIDATE_NOT_CANONICAL"
    assert record.get("advisory_only") is True
    assert record.get("same_factor_not_generalized") is True
    assert record.get("canonical_promotion_allowed") is False
    assert record.get("bias_type") in {"unknown", "unidentified"}, path
    return_source = str(record.get("return_source_hypothesis") or "").casefold()
    assert "conjecture" in return_source and "rival" in return_source, path
    return record


def _target_pfvv_cases(cases):
    return [
        case for case in cases
        if case.get("doc_type") == "knowledge_record"
        and all(case.get(key) == value for key, value in _PFVV_SEED_IDENTITY.items())
    ]


def _target_event_u_cases(cases):
    """Select this optional historical seed, never a PFVV or future case."""

    return [
        case for case in cases
        if case.get("doc_type") == "knowledge_record"
        and all(case.get(key) == value for key, value in _EVENT_U_SEED_IDENTITY.items())
    ]


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def load_step(step: int):
    filename = "standardize_step1_research_fields.py" if step == 1 else f"run_step{step}.py"
    path = REPO / f"skills/factor-forge-step{step}/scripts/{filename}"
    spec = importlib.util.spec_from_file_location(f"step{step}_knowledge_replay", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("query", "expected"), [
    ("open volume correlation low turnover payer", "node::alpha014_momentum_volume_corr_smoothing_20260618"),
    ("occupation measure hidden state partial IC", "node::value_occupation_v18_lebesgue_closeout_20260615"),
    ("economic estimand mathematical model measurement", "node::method_mechanism_conditioned_measurement_search_20260807"),
])
def test_public_history_exposes_reusable_reasoning_without_writes(query, expected):
    before = snapshot(VAULT / "graph")
    result = build_knowledge_reference_contract(
        repo_root=REPO, query_text=query, producer="historical_replay_test", top_k=5,
    )
    assert result["retrieval_status"] == "retrieved"
    node = next(n for n in result["retrieved_cases"] if n["id"] == expected)
    assert node["mechanism"] and node["reuse_guidance"]
    assert node["advisory_only"] is True
    assert Path(node["source_node_path"]).is_file()
    assert result["retrieved_knowledge_relations"]
    assert snapshot(VAULT / "graph") == before


def test_graph_and_experience_lanes_merge_without_weak_hit_masking_or_duplicates(tmp_path, monkeypatch):
    graph_paths = [tmp_path / name for name in ("nodes.jsonl", "edges.jsonl", "taxonomy.json")]
    for path in graph_paths:
        path.write_text("", encoding="utf-8")
    graph_nodes = [
        {"id": "node::graph_primary", "title": "Primary graph case", "summary": "strong graph match"},
        {"id": "node::shared", "title": "Shared graph case", "summary": "deduplicate by ID"},
    ]
    monkeypatch.setattr(
        knowledge_reference,
        "_graph_reference_context",
        lambda **_kwargs: (graph_nodes, [], graph_paths, None),
    )
    index = tmp_path / "experience.jsonl"
    index.write_text(
        "\n".join(
            json.dumps(doc)
            for doc in (
                {
                    "id": "experience::weak_state_overlap",
                    "factor_id": "weak", "search_text": "state",
                    "advisory_projection": {}, "metadata": {},
                },
                {
                    "id": "node::shared", "factor_id": "duplicate",
                    "search_text": "state", "advisory_projection": {}, "metadata": {},
                },
            )
        ),
        encoding="utf-8",
    )

    result = build_knowledge_reference_contract(
        repo_root=tmp_path,
        query_text="occupation measure hidden state partial IC",
        producer="test",
        retrieval_index=index,
        top_k=2,
    )

    assert result["retrieved_case_ids"] == [
        "node::graph_primary", "node::shared", "experience::weak_state_overlap",
    ]
    assert [case["id"] for case in result["retrieved_cases"]] == result["retrieved_case_ids"]
    assert result["hit_count"] == 3
    assert any("Primary graph case" in lesson for lesson in result["similar_case_lessons_imported"])
    assert any("weak" in lesson for lesson in result["similar_case_lessons_imported"])


def test_zero_hit_stays_cold_start_when_both_advisory_lanes_are_empty(tmp_path, monkeypatch):
    graph_paths = [tmp_path / name for name in ("nodes.jsonl", "edges.jsonl", "taxonomy.json")]
    for path in graph_paths:
        path.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        knowledge_reference,
        "_graph_reference_context",
        lambda **_kwargs: ([], [], graph_paths, None),
    )

    result = build_knowledge_reference_contract(
        repo_root=tmp_path,
        query_text="no matching mechanism",
        producer="test",
        retrieval_index=tmp_path / "missing.jsonl",
    )

    assert result["retrieval_status"] == "cold_start"
    assert result["hit_count"] == 0
    assert result["retrieved_cases"] == []


def test_existing_step1_enrichment_preserves_source_hypothesis():
    module = load_step(1)
    aim = {
        "report_id": "SYNTHETIC_KNOWLEDGE_ONLY_NOT_A_FACTOR_RUN",
        "final_factor": {
            "name": "source_defined_object",
            "economic_logic": "liquidity pressure from constrained inventory holders",
        },
        "research_discipline": {
            "economic_hypothesis": {"claim": "the source hypothesis remains primary"},
            "math_hypothesis_candidates": [{"name": "source_defined_mathematical_object"}],
        },
    }
    original = copy.deepcopy(aim)
    enriched = module.attach_factor_knowledge_context(aim)
    assert aim == original
    assert enriched["final_factor"] == original["final_factor"]
    for key in ("economic_hypothesis", "math_hypothesis_candidates"):
        assert enriched["research_discipline"][key] == original["research_discipline"][key]
    assert enriched["research_discipline"]["factor_knowledge_context"]["node_count"] > 0


@pytest.mark.parametrize("step", [1, 2])
def test_actual_corrected_experience_reaches_new_helpers_without_source_substitution(step, monkeypatch):
    """Content regression on the active local seed, not blind research evidence."""
    packaged_seed = VAULT / "workspace_experience_exports" / (
        "knowledge_record__RPT_web_8596d811_20250508_mszq_intraday_momentum_pulse.json"
    )
    has_packaged_correction = (
        packaged_seed.is_file()
        and bool((json.loads(packaged_seed.read_text(encoding="utf-8")).get(
            "package_projection"
        ) or {}).get("source_revision_context_not_replayable"))
    )
    if not _OPTIONAL_EVENT_U_SEED.is_file() and not has_packaged_correction:
        pytest.skip(
            "optional EVENT_U corrected knowledge export is not installed; "
            "this is not PFVV evidence"
        )
    module = load_step(step)
    for name in ("FACTORFORGE_FACTOR_WORKSPACE", "FACTORFORGE_ROOT",
                 "FACTORFORGE_SHARED_FACTORFORGE_ROOT", "FACTORFORGE_RETRIEVAL_INDEX"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL", "1")
    aim = {
        "research_subject_mode": "independent_hypothesis",
        "final_factor": {"name": "new_signed_pressure", "economic_logic": "signed event pressure and price displacement"},
        "research_discipline": {
            "economic_hypothesis": {"claim": "signed pressure may relax over a specified horizon"},
            "math_hypothesis_candidates": [{"name": "causal convolution or Kalman state filter"}],
        },
    }
    before = copy.deepcopy(aim)
    if step == 1:
        contract = module.attach_factor_knowledge_context(aim)["knowledge_reference_contract"]
    else:
        contract = module.build_step2_research_contract(
            {"factor_id": "new_signed_pressure", "raw_formula_text": "signed pressure displacement"},
            {}, aim, {},
        )["knowledge_reference_contract"]
    assert aim == before
    # The optional export being installed is a precondition.  Once installed,
    # an absent, malformed, or non-matching retrieval index must fail below;
    # never turn a cold/empty retrieval result into a skip.
    experiences = _target_event_u_cases(contract["retrieved_cases"])
    assert len(experiences) == 1
    case = experiences[0]
    assert case["research_variant"] == "EVENT_U_SOURCE_EXTENSION"
    assert case["paper_replication_status"] == "PF_VV_AND_COMPOSITE_NOT_REPRODUCED"
    assert case["failure_conditions"] == []
    assert case["mechanism"]["constraint_sources"] == []
    assert case["mechanism"]["objective_constraint_dependency"] == "unknown"
    exported = json.loads((REPO / case["source_path"]).read_text(encoding="utf-8"))
    assert (exported.get("export_revision") or
            (exported.get("package_projection") or {}).get("source_revision_context_not_replayable"))
    assert any("PF_VV_AND_COMPOSITE_NOT_REPRODUCED" in lesson for lesson in contract["similar_case_lessons_imported"])
    assert any(row.get("node_type") == "methodology" for row in contract["retrieved_cases"])


def test_event_u_optional_seed_selection_is_identity_scoped():
    target = {"doc_type": "knowledge_record", **_EVENT_U_SEED_IDENTITY}
    assert _target_event_u_cases([
        target,
        {"doc_type": "knowledge_record", **_EVENT_U_SEED_IDENTITY, "factor_id": "mszq_pfvv_source_baseline"},
        {"doc_type": "knowledge_record", **_EVENT_U_SEED_IDENTITY, "research_variant": "PFVV_SOURCE_BASELINE"},
        {"doc_type": "methodology", **_EVENT_U_SEED_IDENTITY},
    ]) == [target]


@pytest.mark.parametrize("step", [1, 2])
def test_real_pfvv_candidate_seed_reaches_step_consumers_by_mechanism_without_source_substitution(
    step, monkeypatch,
):
    """Acceptance for a packaged PFVV candidate; no seed is fabricated here."""

    seed = _pfvv_candidate_seed_or_skip()
    module = load_step(step)
    for name in (
        "FACTORFORGE_FACTOR_WORKSPACE", "FACTORFORGE_ROOT",
        "FACTORFORGE_SHARED_FACTORFORGE_ROOT", "FACTORFORGE_RETRIEVAL_INDEX",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL", "1")
    aim = {
        "research_subject_mode": "independent_hypothesis",
        "final_factor": {
            "name": "new_intraday_path_dispersion_hypothesis",
            "economic_logic": (
                "temporary price pressure versus permanent information in "
                "same-sign intraday path dispersion"
            ),
            "behavioral_logic": "urgent liquidity demand can be a rival to information arrival",
            "assembly_steps": ["same-sign deviation", "volume-peak path segments"],
        },
        "research_discipline": {
            "economic_hypothesis": {
                "claim": "a new source-specific pressure hypothesis remains primary",
                "payer": "newly hypothesized constrained participant",
            },
            "math_hypothesis_candidates": [
                {"name": "new_observation_equation_for_path_dispersion"},
            ],
            "step1_mathematical_object": "new source mathematical object, not a historical case object",
        },
    }
    before = copy.deepcopy(aim)
    if step == 1:
        result = module.attach_factor_knowledge_context(aim)
        contract = result["knowledge_reference_contract"]
        assert result["research_discipline"]["economic_hypothesis"] == before["research_discipline"]["economic_hypothesis"]
        assert result["research_discipline"]["math_hypothesis_candidates"] == before["research_discipline"]["math_hypothesis_candidates"]
        assert result["research_discipline"]["step1_mathematical_object"] == before["research_discipline"]["step1_mathematical_object"]
    else:
        result = module.build_step2_research_contract(
            {
                "factor_id": "new_intraday_path_dispersion_hypothesis",
                "raw_formula_text": "same-sign deviation and volume-peak path dispersion",
            },
            {}, aim, {},
        )
        contract = result["knowledge_reference_contract"]
        assert result["economic_hypothesis"] == before["research_discipline"]["economic_hypothesis"]
        assert result["math_hypothesis_candidates"] == before["research_discipline"]["math_hypothesis_candidates"]
        assert result["step1_mathematical_object"] == before["research_discipline"]["step1_mathematical_object"]
    assert aim == before
    # The query comes only from mechanism and mathematical-object words above;
    # neither the PFVV report ID nor its factor ID appears in this new source.
    assert "RPT_pdf_11d72_pfvv_20250508_mszq" not in contract["query_terms"]
    assert "mszq_pfvv_source_baseline" not in contract["query_terms"]
    cases = _target_pfvv_cases(contract["retrieved_cases"])
    assert len(cases) == 1
    case = cases[0]
    assert case["advisory_only"] is True
    assert case["not_same_factor_unless_identity_matches"] is True
    assert case["mechanism"]["bias_type"] == seed["bias_type"]
    assert case["mechanism"]["bias_type"] in {"unknown", "unidentified"}
    assert case["mechanism"]["return_source_hypothesis"] == seed["return_source_hypothesis"]
    source_hypothesis = case["mechanism"]["return_source_hypothesis"].casefold()
    assert "conjecture" in source_hypothesis and "rival" in source_hypothesis
    assert case["research_variant"] == seed.get("research_variant")
    assert case["paper_replication_status"] == seed.get("paper_replication_status")
    assert case["reuse_constraints"] == seed.get("reuse_constraints", [])


@pytest.mark.parametrize("step", [1, 2])
@pytest.mark.parametrize("corrupt", [False, True])
def test_real_step_helpers_consume_rebuilt_path_without_overwriting_result(tmp_path, monkeypatch, step, corrupt):
    from scripts.build_factorforge_retrieval_index import make_knowledge_doc

    module = load_step(step)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    record = {
        "report_id": "PREVIOUS_EXPERIENCE", "factor_id": "HISTORICAL_FIXTURE",
        "return_source_hypothesis": "liquidity pressure from constrained holders",
        "failure_patterns": ["Pressure can be an inventory-risk proxy."],
        "reuse_constraints": ["Test inventory risk as a rival explanation."],
    }
    doc = make_knowledge_doc(tmp_path / "historical_record.json", record)
    index = tmp_path / "knowledge/retrieval/factorforge_retrieval_index.jsonl"
    index.parent.mkdir(parents=True)
    index.write_text("{bad" if corrupt else json.dumps(doc))
    aim = {
        "final_factor": {"name": "TEST", "economic_logic": "liquidity pressure"},
        "research_discipline": {},
    }
    before = copy.deepcopy(aim)
    if step == 1:
        contract = module.attach_factor_knowledge_context(aim)["knowledge_reference_contract"]
    else:
        contract = module.build_step2_research_contract(
            {"report_id": "TEST", "factor_id": "TEST", "raw_formula_text": "rank(close)"},
            {}, aim, {},
        )["knowledge_reference_contract"]
    assert aim == before
    assert str(index) in contract["index_paths_checked"]
    if corrupt:
        assert contract["retrieval_status"] == "unavailable"
        assert "malformed_legacy_json" in contract["fallback_reason"]
    else:
        assert contract["retrieved_case_ids"] == ["knowledge_record::PREVIOUS_EXPERIENCE"]
        assert [case["id"] for case in contract["retrieved_cases"]] == contract["retrieved_case_ids"]
        assert contract["retrieved_cases"][0]["reuse_constraints"] == record["reuse_constraints"]
    assert not validate_knowledge_reference_contract(contract, retrieval_required=False)


def test_experience_to_index_to_next_query_keeps_conditions_and_identity(tmp_path):
    # Repackage an already public lesson solely to exercise the storage/index
    # interface. It is not a new research result or an approved memory lesson.
    node = json.loads((VAULT / "graph/nodes/ALPHA014_MOMENTUM_VOLUME_CORR_SMOOTHING_20260618.json").read_text())
    query = "open volume correlation liquidity payer"
    before = build_knowledge_reference_contract(repo_root=tmp_path, query_text=query, producer="test")
    assert before["hit_count"] == 0
    source_dir = tmp_path / "objects/research_knowledge_base"
    source_dir.mkdir(parents=True)
    record = {
        "report_id": "HISTORICAL_ALPHA014_REPLAY_ONLY", "factor_id": "Alpha014",
        "decision": "iterate", "producer": "historical_replay_fixture",
        "success_patterns": [], "failure_patterns": [node["summary"]],
        "modification_hypotheses": ["Test whether the filter deletes payer exposure; not an identified cause."],
        "return_source_hypothesis": node["mechanism"]["economic_hypothesis"],
        "objective_constraint_dependency": "high",
        "expected_failure_regimes": ["A low-turnover filter can remove the volume-pressure state."],
        "reuse_constraints": [node["evidence"]["falsification"]],
        "source_identity": {"report_id": "HISTORICAL_ALPHA014_REPLAY_ONLY"},
        "research_memo": {"unreviewed_evo_diagnostic": "MUST_NOT_BECOME_REUSABLE_KNOWLEDGE"},
    }
    source = source_dir / "knowledge_record__replay.json"
    source.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    source_before = source.read_bytes()
    subprocess.run([
        sys.executable, str(REPO / "scripts/build_factorforge_retrieval_index.py"),
        "--runtime-root", str(tmp_path),
    ], check=True, capture_output=True, text=True)
    after = build_knowledge_reference_contract(repo_root=tmp_path, query_text=query, producer="next_research_test")
    assert after["retrieved_case_ids"] == ["knowledge_record::HISTORICAL_ALPHA014_REPLAY_ONLY"]
    case = after["retrieved_cases"][0]
    assert case["mechanism"]["return_source_hypothesis"] == record["return_source_hypothesis"]
    assert case["failure_conditions"] == record["expected_failure_regimes"]
    assert case["reuse_constraints"] == record["reuse_constraints"]
    assert case["identity"]["source_identity"] == record["source_identity"]
    assert case["modification_hypotheses"][0]["status"] == "candidate_not_verified"
    assert case["advisory_only"] and case["not_same_factor_unless_identity_matches"]
    assert "MUST_NOT_BECOME_REUSABLE_KNOWLEDGE" not in json.dumps(after)
    assert source.read_bytes() == source_before
    assert validate_knowledge_reference_contract(after, retrieval_required=True) == []


def test_step6_receives_conditions_and_rival_candidate_not_only_truncated_snippet(tmp_path, monkeypatch):
    from scripts.build_factorforge_retrieval_index import make_knowledge_doc

    module = load_step(6)
    record = {
        "report_id": "PRIOR_SYNTHETIC_CASE", "factor_id": "PRIOR",
        "return_source_hypothesis": "inventory liquidity pressure",
        "failure_patterns": ["A liquidity filter may delete payer information."],
        "modification_hypotheses": ["Hold turnover fixed and test payer exposure."],
        "expected_failure_regimes": ["one-sided liquidity"],
        "reuse_constraints": ["A rival explanation, not an identified current cause."],
    }
    doc = make_knowledge_doc(tmp_path / "prior.json", record)
    monkeypatch.setattr(module, "load_retrieval_docs", lambda: [doc])
    monkeypatch.setenv("FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL", "1")
    monkeypatch.setenv("FACTORFORGE_DISABLE_GRAPH_KNOWLEDGE_CONTEXT", "1")
    bundle = {
        "factor_run_master": {"report_id": "CURRENT_SYNTHETIC_CASE", "factor_id": "CURRENT"},
        "factor_case_master": {"lessons": ["inventory liquidity pressure"], "next_actions": []},
    }
    context = module.build_retrieval_context(bundle, payloads={})
    advisory = context["similar_cases"][0]["advisory_context"]
    assert advisory["failure_conditions"] == record["expected_failure_regimes"]
    assert advisory["reuse_constraints"] == record["reuse_constraints"]
    assert advisory["modification_hypotheses"][0]["status"] == "candidate_not_verified"
    assert advisory["advisory_only"] is True


@pytest.mark.parametrize("body", ['{bad', '[]', '{"id":"one"}\n{"id":"one"}', '{"id":"one","advisory_projection":[]}'])
def test_step6_bad_experience_index_is_visible_and_nonblocking(tmp_path, monkeypatch, body):
    module = load_step(6)
    index = tmp_path / "index.jsonl"
    index.write_text(body)
    monkeypatch.setattr(module, "RETRIEVAL_INDEX", index)
    monkeypatch.setenv("FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL", "1")
    monkeypatch.setenv("FACTORFORGE_DISABLE_GRAPH_KNOWLEDGE_CONTEXT", "1")
    bundle = {
        "factor_run_master": {"report_id": "CURRENT", "factor_id": "CURRENT"},
        "factor_case_master": {"lessons": ["liquidity pressure"], "next_actions": []},
    }
    before = copy.deepcopy(bundle)
    context = module.build_retrieval_context(bundle, payloads={})
    assert context["retrieval_index_readable"] is False
    assert context["retrieval_error"]
    assert not context["similar_cases"]
    assert bundle == before
    assert index.read_text() == body


@pytest.mark.parametrize("bad_index", ["{bad\n", "[]\n", '{"text":"liquidity"}\n', '{"id":"x","text":"liquidity"}\n' * 2])
def test_invalid_index_is_unavailable_not_a_missing_prior(tmp_path, bad_index):
    path = tmp_path / "knowledge/retrieval/factorforge_retrieval_index.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(bad_index)
    before = snapshot(tmp_path)
    result = build_knowledge_reference_contract(repo_root=tmp_path, query_text="liquidity", producer="test")
    assert result["retrieval_status"] == "unavailable"
    assert validate_knowledge_reference_contract(result, retrieval_required=True)
    # Optional advisory failure must not hold the source research hostage.
    assert not validate_knowledge_reference_contract(result, retrieval_required=False)
    assert snapshot(tmp_path) == before


def test_partial_graph_and_empty_query_are_not_false_hits(tmp_path):
    root = tmp_path / "knowledge/因子工厂"
    (root / "graph").mkdir(parents=True)
    (root / "graph/factor_knowledge_nodes.jsonl").write_text("")
    partial = build_knowledge_reference_contract(repo_root=tmp_path, query_text="liquidity", producer="test")
    assert partial["retrieval_status"] == "unavailable"
    empty = build_knowledge_reference_contract(repo_root=REPO, query_text="  ", producer="test")
    assert empty["hit_count"] == 0 and not empty["retrieved_cases"]


@pytest.mark.parametrize("top_k", [0, -1, True, "3"])
def test_top_k_must_be_positive_integer(top_k):
    with pytest.raises(ValueError, match="positive integer"):
        build_knowledge_reference_contract(repo_root=REPO, query_text="liquidity", producer="test", top_k=top_k)


def test_explicit_graph_resolves_its_nodes_and_never_installed_copy(tmp_path):
    graph = tmp_path / "exported_graph"
    shutil.copytree(VAULT / "graph", graph)
    expected = graph / "nodes/ALPHA014_MOMENTUM_VOLUME_CORR_SMOOTHING_20260618.json"
    raw = "/old/checkout/knowledge/因子工厂/graph/nodes/" + expected.name
    assert resolve_graph_node_path(raw, graph_root=graph) == expected
    for path in ["../escape.json", "/other/export/node.json"]:
        with pytest.raises(KnowledgeRetrievalError):
            resolve_graph_node_path(path, graph_root=graph)
    result = retrieve_factor_knowledge_context(
        text="open volume correlation", node_index=graph / "factor_knowledge_nodes.jsonl",
        edge_index=graph / "factor_knowledge_edges.jsonl", graph_root=graph,
    )
    assert all(Path(node["source_node_path"]).is_relative_to(graph) for node in result["nodes"])


def test_new_named_math_reference_is_not_mislabelled_as_empirical_factor(monkeypatch):
    # This assertion is about exact lexical routing, independent of a user's
    # optional local semantic model and its additional related references.
    monkeypatch.setenv("FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL", "1")
    result = build_knowledge_reference_contract(repo_root=REPO, query_text="小波分析", producer="test")
    assert result["hit_count"] == 1
    assert "node::method_transient_signal_models_20260907" in str(result)
    assert "reference_only_no_empirical_claim" in str(result)
