"""Selected-workspace semantics and old CLI/library parity for Step6 helpers."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from factor_factory.revision_council import agentic_result, collection
from factor_factory.step6.journal import build_researcher_dossier
from factor_factory.step6.packets import build_researcher_packet


ROOT = Path(__file__).resolve().parents[1]
RID = "LIBRARY_STEP6"


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def _council(root):
    return root / "objects/research_iteration_master/revision_council" / RID


def test_task_and_result_lookups_use_explicit_workspace_not_ambient_root(tmp_path, monkeypatch):
    actual, ambient = tmp_path / "actual", tmp_path / "ambient"
    monkeypatch.setenv("FACTORFORGE_ROOT", str(ambient))
    for root, marker in [(actual, "selected"), (ambient, "wrong-study")]:
        _write(_council(root) / f"agentic_taskbook__{RID}.json", {
            "research_protocol_version": agentic_result.RESEARCH_PROTOCOL_VERSION,
            "agent_tasks": [{"task_id": "T1", "marker": marker}],
        })
        _write(_council(root) / f"dispatch_manifest__{RID}.json", {
            "agent_tasks": [{"task_id": "T1", "expected_result_path": "result.json", "marker": marker}],
        })
    assert agentic_result.protocol_task(RID, "T1", workspace_root=actual)["marker"] == "selected"
    assert agentic_result.expected_manifest_task(RID, actual / "result.json", workspace_root=actual)["marker"] == "selected"
    assert agentic_result.expected_manifest_task(RID, ambient / "result.json", workspace_root=actual) == {}


@pytest.mark.parametrize("bad_hash", [False, True])
def test_collection_checks_declared_results_in_selected_workspace(tmp_path, monkeypatch, bad_hash):
    actual = tmp_path / "actual"
    monkeypatch.setenv("FACTORFORGE_ROOT", str(tmp_path / "wrong-study"))
    result_path = _write(actual / "result.json", {"status": "final"})
    value = {
        "collection_version": collection.COLLECTION_VERSION, "report_id": RID,
        "required_result_count": 1, "present_result_count": 1, "valid_result_count": 1,
        "invalid_result_count": 0, "missing_result_count": 0, "ready_for_finalize": True,
        "status": "complete", "valid_results": [{
            "status": "final", "task_id": "T1", "result_path": "result.json",
            "result_sha256": "0" * 64 if bad_hash else hashlib.sha256(result_path.read_bytes()).hexdigest(),
        }],
    }
    reasons = collection.validate_collection(RID, value, workspace_root=actual)
    assert reasons == (["BLOCK_AGENTIC_COUNCIL_COLLECTION_RESULT_HASH_MISMATCH"] if bad_hash else [])


@pytest.mark.parametrize("name,library,symbol", [
    ("validate_agentic_council_result", agentic_result, "validate_agentic_result"),
    ("validate_agentic_council_collection", collection, "validate_collection"),
])
def test_old_validator_imports_and_cli_match_installed_library_shape(tmp_path, name, library, symbol):
    script = ROOT / "skills/factor-forge-step6/scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"compat_{name}", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert getattr(module, symbol) is getattr(library, symbol)
    args = [sys.executable, "-B", str(script), "--report-id", RID]
    if symbol == "validate_agentic_result":
        path = _write(tmp_path / "result.json", {})
        expected = library.validate_agentic_result({}, expected_task={}, expected_report_id=RID, workspace_root=tmp_path)
        args += ["--result-path", str(path)]
    else:
        _write(_council(tmp_path) / f"agentic_result_collection__{RID}.json", {})
        expected = library.validate_collection(RID, {}, workspace_root=tmp_path)
    run = subprocess.run(args, cwd=tmp_path, env={**os.environ, "FACTORFORGE_ROOT": str(tmp_path)},
                         text=True, capture_output=True, timeout=30)
    assert run.returncode == 1, run.stderr
    payload = json.loads(run.stdout)
    actual = payload["results"][0]["block_reasons"] if symbol == "validate_agentic_result" else payload["block_reasons"]
    assert actual == expected


def test_dossier_and_packet_preserve_sources_and_resolve_relative_evidence(tmp_path, monkeypatch):
    root = tmp_path / "study"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    _write(root / f"objects/factor_spec_master/factor_spec_master__{RID}.json", {"factor_id": "CURRENT", "hypothesis": "source hypothesis"})
    _write(root / f"objects/factor_run_master/factor_run_master__{RID}.json", {
        "evaluation_results": {"backend_runs": [{"backend": "ic", "payload_path": "evaluations/ic.json"}]},
    })
    _write(root / "evaluations/ic.json", {"metrics": {"rank_ic_mean": -0.2}, "artifacts": {"head": "samples/head.json"}})
    _write(root / "samples/head.json", {"factor_value": 0.0})
    memo = _write(root / f"objects/research_iteration_master/researcher_memo__{RID}.json", {
        "producer": "independent_researcher", "researcher_decision": "reject",
    })
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    packet = build_researcher_packet(RID, workspace_root=root)
    dossier = build_researcher_dossier(RID, workspace_root=root)
    assert packet["backend_payloads"]["ic"]["metrics"]["rank_ic_mean"] == -0.2
    assert packet["backend_artifacts"]["ic"][0]["exists"] is True
    assert packet["required_researcher_output"] == str(memo)
    assert packet["source_files"]["prior_researcher_memo"]["exists"] is True
    assert "prior_researcher_memo" not in packet["objects"]
    assert dossier["object_files"]["factor_spec_master"][0]["preview"]["factor_id"] == "CURRENT"
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert list(elsewhere.iterdir()) == []


@pytest.mark.parametrize("module,legacy,expected_name", [
    ("journal", "factor-forge-researcher/scripts/build_researcher_dossier.py", "researcher_dossier"),
    ("packets", "factor-forge-step6-researcher/scripts/build_researcher_packet.py", "researcher_packet"),
])
def test_module_cli_and_legacy_packet_cli_are_equivalent(tmp_path, module, legacy, expected_name):
    output1, output2 = tmp_path / "module.json", tmp_path / "legacy.json"
    env = {**os.environ, "FACTORFORGE_ROOT": str(tmp_path / "study"), "PYTHONPATH": str(ROOT)}
    commands = [[sys.executable, "-B", "-m", f"factor_factory.step6.{module}"],
                [sys.executable, "-B", str(ROOT / "skills" / legacy)]]
    for command, output in zip(commands, [output1, output2]):
        run = subprocess.run([*command, "--report-id", RID, "--output", str(output)], cwd=tmp_path,
                             env=env, text=True, capture_output=True, timeout=30)
        assert run.returncode == 0, run.stderr
    assert json.loads(output1.read_text()) == json.loads(output2.read_text())
    assert expected_name in json.loads(output1.read_text())["producer"]
