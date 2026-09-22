from __future__ import annotations

import argparse
import ast
import importlib.util
import json
from pathlib import Path

import pytest

from factor_factory.knowledge_reference import resolve_runtime_retrieval_index
import scripts.run_factorforge_ultimate as ultimate
from scripts.run_factorforge_ultimate import run_post_step6_knowledge_refresh_nonblocking


def _record(report_id: str, *, bad: bool = False) -> dict:
    historical = report_id == "HISTORICAL"
    record: dict = {
        "report_id": report_id,
        "factor_id": "PV_SHOCK",
        "decision": "iterate",
        "success_patterns": ["liquidity shock mean reversion"] if historical else ["current record only"],
        "failure_patterns": ["one-sided queue"],
        "modification_hypotheses": ["shorter liquidity window"],
        "factor_family": "price_volume",
        "monetization_model": "underreaction",
        "bias_type": "behavioral",
        "return_source_hypothesis": "liquidity shock is incorporated slowly" if historical else "current execution record",
        "expected_failure_regimes": ["limit queue"],
        "objective_constraint_dependency": "high",
        "constraint_sources": ["price limit"],
        "reuse_constraints": ["identity must match"],
        "artifact_identity": {"formula_hash": f"formula-{report_id}"},
    }
    if bad:
        record["failure_patterns"] = "not-a-list"
    return record


def _write_record(workspace: Path, report_id: str, *, bad: bool = False) -> Path:
    path = workspace / "objects/research_knowledge_base" / f"knowledge_record__{report_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_record(report_id, bad=bad)), encoding="utf-8")
    return path


def _proof(*, status: str = "PASS", satisfied: bool = True, duplicate_validate: bool = False) -> dict:
    commands = [
        {"name": "run_step6", "status": "PASS", "returncode": 0},
        {"name": "validate_step6", "status": "PASS", "returncode": 0},
    ]
    if duplicate_validate:
        commands.append({"name": "validate_step6", "status": "PASS", "returncode": 0})
    return {
        "status": status,
        "commands": commands,
        "formal_command_contract": {"satisfied": satisfied},
    }


def _args(report_id: str = "CURRENT", *, dry_run: bool = False) -> argparse.Namespace:
    return argparse.Namespace(report_id=report_id, dry_run=dry_run)


def _load_script(name: str, relative_path: str):
    path = Path(__file__).parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_completed_step6_refreshes_workspace_and_next_readers_use_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "factor-workspace"
    default_root = tmp_path / "default-project"
    (default_root / "objects").mkdir(parents=True)
    import scripts.build_factorforge_retrieval_index as indexer
    monkeypatch.setattr(ultimate, "REPO_ROOT", default_root)
    monkeypatch.setattr(indexer, "REPO_ROOT", default_root)
    _write_record(workspace, "HISTORICAL")
    _write_record(workspace, "CURRENT")
    proof = _proof()

    result = run_post_step6_knowledge_refresh_nonblocking(
        args=_args(), proof=proof, factor_workspace=workspace
    )

    index = workspace / "knowledge/retrieval/factorforge_retrieval_index.jsonl"
    assert {key: result[key] for key in ("status", "doc_count", "index_path")} == {
        "status": "REFRESHED", "doc_count": 2, "index_path": str(index),
    }
    assert result["workspace_experience_export"]["status"] == "EXPORTED"
    assert result["default_readback"] is True
    assert result["semantic_index_refresh"]["status"] == "SKIPPED"
    assert result["default_index_path"] == str(
        default_root / "knowledge/retrieval/factorforge_retrieval_index.jsonl"
    )
    assert index.is_file()

    monkeypatch.setenv("FACTORFORGE_ROOT", str(workspace))
    monkeypatch.setenv("FACTORFORGE_SHARED_FACTORFORGE_ROOT", str(tmp_path / "shared"))
    monkeypatch.setenv("FACTORFORGE_FACTOR_WORKSPACE", str(workspace))
    monkeypatch.setenv("FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL", "1")
    step1 = _load_script(
        "test_step1_knowledge_refresh_reader",
        "skills/factor-forge-step1/scripts/standardize_step1_research_fields.py",
    )
    aim = {
        "final_factor": {"economic_logic": "liquidity shock", "name": "new name"},
        "research_discipline": {
            "economic_hypothesis": {"claim": "liquidity shock"},
            "math_hypothesis_candidates": ["wavelet energy"],
        },
    }
    enriched = step1.attach_factor_knowledge_context(aim)
    contract = enriched["knowledge_reference_contract"]
    assert str(index) in contract["indexes_available"]
    assert any(case.get("report_id") == "HISTORICAL" for case in contract["retrieved_cases"])
    assert enriched["final_factor"] == aim["final_factor"]
    assert enriched["research_discipline"]["economic_hypothesis"] == aim["research_discipline"]["economic_hypothesis"]
    assert enriched["research_discipline"]["math_hypothesis_candidates"] == ["wavelet energy"]

    step2 = _load_script(
        "test_step2_knowledge_refresh_reader",
        "skills/factor-forge-step2/scripts/run_step2.py",
    )
    step2_contract = step2.build_step2_research_contract(
        {"report_id": "NEXT", "factor_id": "NEXT", "raw_formula_text": "rank(close)"},
        {}, aim, {},
    )["knowledge_reference_contract"]
    assert str(index) in step2_contract["indexes_available"]
    assert any(case.get("report_id") == "HISTORICAL" for case in step2_contract["retrieved_cases"])

    step6 = _load_script(
        "test_step6_knowledge_refresh_reader",
        "skills/factor-forge-step6/scripts/run_step6.py",
    )
    assert step6.RETRIEVAL_INDEX == index
    context = step6.build_retrieval_context(
        {"factor_run_master": {"report_id": "CURRENT", "factor_id": "PV_SHOCK"},
         "factor_case_master": {"factor_id": "PV_SHOCK", "lessons": ["liquidity shock"], "next_actions": [], "final_status": "iterate"}},
        {},
    )
    assert any(case["report_id"] == "HISTORICAL" for case in context["similar_cases"])
    assert all(case["report_id"] != "CURRENT" for case in context["similar_cases"])


@pytest.mark.parametrize(
    "proof,dry_run,workspace",
    [
        (_proof(), True, True),
        (_proof(status="PAUSED"), False, True),
        (_proof(status="FAIL"), False, True),
        ({"status": "PASS", "commands": [], "formal_command_contract": {"satisfied": True}}, False, True),
        (_proof(satisfied=False), False, True),
        (_proof(duplicate_validate=True), False, True),
        (_proof(), False, False),
    ],
    ids=["dry-run", "paused", "failed", "no-step6", "contract", "duplicate-validator", "no-workspace"],
)
def test_ineligible_refresh_never_writes(
    tmp_path: Path, proof: dict, dry_run: bool, workspace: bool
) -> None:
    root = tmp_path / "workspace"
    if workspace:
        _write_record(root, "CURRENT")
    result = run_post_step6_knowledge_refresh_nonblocking(
        args=_args(dry_run=dry_run), proof=proof, factor_workspace=root if workspace else None
    )
    assert result["status"] == "SKIPPED"
    assert not (root / "knowledge/retrieval/factorforge_retrieval_index.jsonl").exists()


def test_bad_source_preserves_index_proof_and_objects_with_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    source = _write_record(workspace, "CURRENT", bad=True)
    source_bytes = source.read_bytes()
    index = workspace / "knowledge/retrieval/factorforge_retrieval_index.jsonl"
    index.parent.mkdir(parents=True)
    index.write_bytes(b"old-index\n")
    proof = _proof()
    proof_bytes = json.dumps(proof, sort_keys=True).encode()

    result = run_post_step6_knowledge_refresh_nonblocking(
        args=_args(), proof=proof, factor_workspace=workspace
    )

    captured = capsys.readouterr()
    assert result["status"] == "REFRESH_FAILED"
    assert index.read_bytes() == b"old-index\n"
    assert source.read_bytes() == source_bytes
    assert json.dumps(proof, sort_keys=True).encode() == proof_bytes
    assert "[KNOWLEDGE_WARNING]" in captured.out


def test_create_only_export_conflict_is_visible_without_changing_step6_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / 'workspace'
    default_root = tmp_path / 'default'
    (default_root / 'objects').mkdir(parents=True)
    import scripts.build_factorforge_retrieval_index as indexer
    monkeypatch.setattr(ultimate, 'REPO_ROOT', default_root)
    monkeypatch.setattr(indexer, 'REPO_ROOT', default_root)
    source = _write_record(workspace, 'CURRENT')

    from factor_factory.workspace_experience_export import export_workspace_knowledge_record
    export_workspace_knowledge_record(
        workspace=workspace, repo_root=default_root, report_id='CURRENT'
    )
    source.write_text(json.dumps({**_record('CURRENT'), 'failure_patterns': ['changed']}), encoding='utf-8')

    result = run_post_step6_knowledge_refresh_nonblocking(
        args=_args(), proof=_proof(), factor_workspace=workspace
    )

    assert result['status'] == 'REFRESHED'
    assert result['workspace_experience_export'] == {
        'status': 'EXPORT_FAILED', 'error_type': 'FileExistsError',
    }
    assert '[KNOWLEDGE_WARNING] workspace experience export failed (FileExistsError)' in capsys.readouterr().out


def test_semantic_refresh_failure_preserves_completed_export(tmp_path, monkeypatch):
    import factor_factory.semantic_knowledge_retrieval as semantic
    workspace, repo = tmp_path/'workspace', tmp_path/'repo'
    repo.mkdir()
    _write_record(workspace, 'CURRENT')
    monkeypatch.setattr(ultimate, 'REPO_ROOT', repo)
    called = []
    def unavailable(root):
        called.append(root)
        raise ImportError('optional model unavailable')
    monkeypatch.setattr(semantic, 'refresh_configured_index', unavailable)
    result = run_post_step6_knowledge_refresh_nonblocking(
        args=_args(), proof=_proof(), factor_workspace=workspace)
    assert called == [repo]
    assert result['workspace_experience_export']['status'] == 'EXPORTED'
    assert result['default_readback'] is True
    assert result['semantic_index_refresh'] == {'status':'FAILED', 'error_type':'ImportError'}


def test_runtime_resolver_isolated_priority_and_explicit_override(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    shared = tmp_path / "shared"
    other_workspace = tmp_path / "other-workspace"
    workspace_index = workspace / "knowledge/retrieval/factorforge_retrieval_index.jsonl"
    shared_index = shared / "knowledge/retrieval/factorforge_retrieval_index.jsonl"
    other_index = other_workspace / "knowledge/retrieval/factorforge_retrieval_index.jsonl"
    for path in (workspace_index, shared_index, other_index):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    env = {"FACTORFORGE_FACTOR_WORKSPACE": str(workspace), "FACTORFORGE_SHARED_FACTORFORGE_ROOT": str(shared)}
    assert resolve_runtime_retrieval_index(tmp_path, environ=env) == workspace_index
    workspace_index.unlink()
    assert resolve_runtime_retrieval_index(tmp_path, environ=env) == shared_index
    missing = tmp_path / "explicit-missing.jsonl"
    assert resolve_runtime_retrieval_index(tmp_path, environ={**env, "FACTORFORGE_RETRIEVAL_INDEX": str(missing)}) == missing
    # `other_workspace` is intentionally populated but undiscoverable: no scan.
    assert resolve_runtime_retrieval_index(tmp_path, environ={}) == tmp_path / "knowledge/retrieval/factorforge_retrieval_index.jsonl"
    assert other_index.exists()


def test_wrapper_hook_is_post_proof_maintenance_not_a_formal_command() -> None:
    source = (Path(__file__).parents[1] / "scripts/run_factorforge_ultimate.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_post_step6_knowledge_refresh_nonblocking")
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "append"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "commands"
        for node in ast.walk(helper)
    )
    call_position = source.rfind("run_post_step6_knowledge_refresh_nonblocking(")
    final_write_position = source.rfind("write_json_atomic(proof_path, proof)", 0, call_position)
    assert final_write_position >= 0 and final_write_position < call_position
    # This is a controlled maintenance wiring assertion, not a formal factor run.
