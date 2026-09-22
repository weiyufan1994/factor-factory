from __future__ import annotations

import os
import json
import subprocess
import sys
import zipfile
from pathlib import Path
import pytest

from scripts.build_factorforge_knowledge_preview import GRAPH_FILES, PACKAGE_FILES, build_preview


REPO = Path(__file__).resolve().parents[1]


def test_builder_creates_portable_zip_without_private_or_research_payloads(tmp_path: Path) -> None:
    output = tmp_path / "preview.zip"
    result = build_preview(source_root=REPO, output=output)
    assert result == output.resolve()
    names = set(zipfile.ZipFile(output).namelist())
    assert "query_knowledge.py" in names
    assert "knowledge/因子工厂/graph/factor_knowledge_nodes.jsonl" in names
    assert not any(name.startswith("/") or ".." in Path(name).parts for name in names)
    with zipfile.ZipFile(output) as zf:
        graph_names = [name for name in names if name.startswith("knowledge/")]
        all_bytes = b"".join(zf.read(name) for name in graph_names)
    assert b"key_metrics" not in all_bytes
    assert b"/Users/" not in all_bytes
    assert b"/home/" not in all_bytes
    assert b"/private/" not in all_bytes
    assert b"/tmp/" not in all_bytes
    assert not any(".pdf" in name.lower() or "oos" in name.lower() for name in names)
    try:
        build_preview(source_root=REPO, output=output)
    except FileExistsError:
        pass
    else:
        raise AssertionError("builder must refuse overwrite")


def test_extracted_cli_runs_from_other_cwd_without_pythonpath(tmp_path: Path) -> None:
    archive = tmp_path / "preview.zip"
    build_preview(source_root=REPO, output=archive)
    extract = tmp_path / "extracted"
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(extract)
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    for query in ("占用测度 价值 支撑", "open volume correlation low turnover payer", "economic estimand mathematical model measurement", "小波分析", "zzuncoveredq42", "  "):
        run = subprocess.run(
            [sys.executable, str(extract / "query_knowledge.py"), "--query", query, "--json"],
            cwd=tmp_path,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(run.stdout)
        assert payload["preview_only"] is True
        if query in {"占用测度 价值 支撑", "open volume correlation low turnover payer", "economic estimand mathematical model measurement"}:
            assert payload["reference"]["hit_count"] > 0
        if not query.strip() or query == "zzuncoveredq42":
            assert payload["reference"]["hit_count"] == 0


def test_compact_cli_output_is_human_readable(tmp_path: Path) -> None:
    archive = tmp_path / "preview.zip"
    build_preview(source_root=REPO, output=archive)
    extract = tmp_path / "extracted"
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(extract)
    run = subprocess.run([sys.executable, str(extract / "query_knowledge.py"), "--query", "占用测度 价值"], cwd=tmp_path, check=True, capture_output=True, text=True)
    assert "advisory-only" in run.stdout
    assert "Hits:" in run.stdout


def test_builder_rejects_symlinked_source_node(tmp_path: Path) -> None:
    source = tmp_path / "source"
    import shutil
    for relative in PACKAGE_FILES + GRAPH_FILES:
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, target)
    shutil.copytree(REPO / "knowledge/因子工厂/graph/nodes", source / "knowledge/因子工厂/graph/nodes", symlinks=True)
    node = source / "knowledge/因子工厂/graph/nodes/ALPHA007_REGIME_KURT_SKEW_20260422.json"
    node.unlink()
    node.symlink_to(REPO / "knowledge/因子工厂/graph/nodes/ALPHA007_REGIME_KURT_SKEW_20260422.json")
    try:
        build_preview(source_root=source, output=tmp_path / "bad.zip")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("symlinked source node must be rejected")


@pytest.mark.parametrize("query, expected", [("MAD sparse event execution constraint", "node::method_sparse_event_projection_failure_20260907"), ("小波分析", "node::method_transient_signal_models_20260907")])
def test_new_reference_nodes_are_queryable(query: str, expected: str, tmp_path: Path) -> None:
    archive = tmp_path / "preview.zip"
    build_preview(source_root=REPO, output=archive)
    extract = tmp_path / "extracted"
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(extract)
    run = subprocess.run([sys.executable, str(extract / "query_knowledge.py"), "--query", query, "--json"], cwd=tmp_path, check=True, capture_output=True, text=True)
    payload = json.loads(run.stdout)
    assert payload["reference"]["hit_count"] > 0
    assert expected in payload["reference"]["retrieved_case_ids"]


def _copy_preview_inputs(source: Path) -> None:
    import shutil
    for relative in PACKAGE_FILES + GRAPH_FILES:
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, target)
    shutil.copytree(REPO / "knowledge/因子工厂/graph/nodes", source / "knowledge/因子工厂/graph/nodes")


def test_explicit_workspace_export_is_scrubbed_and_queryable_offline(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _copy_preview_inputs(source)
    export = source / "knowledge/因子工厂/workspace_experience_exports/knowledge_record__CASE_A.json"
    export.parent.mkdir(parents=True)
    export.write_text(json.dumps({
        "report_id": "CASE_A", "factor_id": "old_factor", "decision": "iterate",
        "export_version": "factorforge_workspace_experience_export_v1",
        "advisory_only": True, "same_factor_not_generalized": True,
        "canonical_promotion_allowed": False,
        "export_status": "LOCAL_PROJECT_ADVISORY_CANDIDATE_NOT_CANONICAL",
        "factor_family": "price_volume", "monetization_model": "constraint", "bias_type": "none",
        "return_source_hypothesis": "rare pressure mechanism",
        "expected_failure_regimes": ["rare failure regime"],
        "objective_constraint_dependency": "rare observation constraint", "constraint_sources": [],
        "success_patterns": [], "failure_patterns": ["rare failure regime"],
        "modification_hypotheses": ["future idea only"],
        "mathematical_object": "rare robust projection",
        "reusable_operator": {"mapping": "rare session operator"},
        "implementation_references": ["/Users/private/implementation.py"],
        "reuse_constraints": ["advisory only; same factor required"],
        "source_record_relative_ref": "objects/research_knowledge_base/knowledge_record__CASE_A.json",
        "metrics": {"annual_return": 999.0},
    }), encoding="utf-8")
    archive = tmp_path / "preview.zip"
    build_preview(source_root=source, output=archive)
    with zipfile.ZipFile(archive) as zf:
        index_name = "knowledge/retrieval/factorforge_retrieval_index.jsonl"
        assert index_name in zf.namelist()
        raw = zf.read(index_name)
        assert b"999" not in raw
        assert b"/Users/" not in raw
        assert b"objects/research_knowledge_base/knowledge_record__CASE_A.json" in raw
        zf.extractall(tmp_path / "extracted")
    run = subprocess.run(
        [sys.executable, str(tmp_path / "extracted/query_knowledge.py"), "--query", "rare robust projection session operator failure regime", "--json"],
        cwd=tmp_path, check=True, capture_output=True, text=True,
    )
    reference = json.loads(run.stdout)["reference"]
    assert "knowledge_record::CASE_A" in reference["retrieved_case_ids"]
    assert len(reference["retrieved_case_ids"]) == len(set(reference["retrieved_case_ids"]))
    case = next(row for row in reference["retrieved_cases"] if row["id"] == "knowledge_record::CASE_A")
    assert case["source_path"] == "knowledge/experience_previews/knowledge_record__CASE_A.json"
    assert (tmp_path / "extracted" / case["source_path"]).is_file()
    assert case["failure_patterns"] == ["rare failure regime"]
    assert case["reuse_constraints"] == ["advisory only; same factor required"]
    assert case["advisory_only"] is True


def test_preview_without_workspace_export_remains_queryable(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _copy_preview_inputs(source)
    archive = tmp_path / "preview.zip"
    build_preview(source_root=source, output=archive)
    with zipfile.ZipFile(archive) as zf:
        assert "knowledge/retrieval/factorforge_retrieval_index.jsonl" not in zf.namelist()
        zf.extractall(tmp_path / "extracted")
    run = subprocess.run(
        [sys.executable, str(tmp_path / "extracted/query_knowledge.py"), "--query", "占用测度 价值 支撑", "--json"],
        cwd=tmp_path, check=True, capture_output=True, text=True,
    )
    assert json.loads(run.stdout)["reference"]["hit_count"] > 0
